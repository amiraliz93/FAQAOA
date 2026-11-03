// g++ qaoa_sim.cpp -o qaoa_sim --std=c++20 -O3
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <vector>
#include <fstream>
#include <iostream>
#include <chrono>

static inline void die(const char* msg) {
    std::cerr << msg << std::endl;
    std::exit(1);
}

static inline void read_exact(std::ifstream& f, void* p, std::size_t n) {
    f.read(reinterpret_cast<char*>(p), static_cast<std::streamsize>(n));
    if (!f) die("qaoa_sim: input read failed");
}

static inline uint32_t swap_bits(uint32_t i, uint32_t a, uint32_t b) {
    const uint32_t ba = (i >> a) & 1u;
    const uint32_t bb = (i >> b) & 1u;
    if (ba != bb) i ^= (1u << a) | (1u << b);
    return i;
}

static inline void write_hex_fixed(FILE* fp, double x, int frac_bits) {
    // Python round() uses nearest/even. nearbyint() follows the default IEEE
    // FE_TONEAREST rounding mode on normal C/C++ runtimes.
    double scaled = std::ldexp(x, frac_bits);
    int64_t q = static_cast<int64_t>(std::nearbyint(scaled));
    uint64_t u = static_cast<uint64_t>(q);
    std::fprintf(fp, "0x%016llx\n", static_cast<unsigned long long>(u));
}

int main(int argc, char** argv) {
    const char* input_path  = (argc > 1) ? argv[1] : "qaoa_sim_input.bin";
    const char* output_path = (argc > 2) ? argv[2] : "qaoa_sim_output.bin";
    const char* result_path = (argc > 3) ? argv[3] : "result.txt";

    std::ifstream in(input_path, std::ios::binary);
    if (!in) die("qaoa_sim: cannot open input file");

    uint32_t magic = 0, NQ = 0, Np = 0, NS = 0;
    read_exact(in, &magic, sizeof(magic));
    read_exact(in, &NQ, sizeof(NQ));
    read_exact(in, &Np, sizeof(Np));
    read_exact(in, &NS, sizeof(NS));
    if (magic != 0x51414F41u) die("qaoa_sim: bad input magic");
    if (NS != (1u << NQ)) die("qaoa_sim: NS != 1 << NQ");

    std::vector<double> re(NS), im(NS), H(NS), gamma(Np), cb(Np), sb(Np);
    read_exact(in, re.data(), sizeof(double) * NS);
    read_exact(in, im.data(), sizeof(double) * NS);
    read_exact(in, H.data(), sizeof(double) * NS);
    read_exact(in, gamma.data(), sizeof(double) * Np);
    read_exact(in, cb.data(), sizeof(double) * Np);
    read_exact(in, sb.data(), sizeof(double) * Np);

    constexpr double TWO_PI = 6.2831853071795864769252867665590057683943387987502;

    // Measure only the simulation compute kernel.
    // This excludes all input loading above and all output/result writing below.
    const auto compute_t0 = std::chrono::steady_clock::now();

    for (uint32_t p = 0; p < Np; ++p) {
        const double g = gamma[p];
        const double c_b = cb[p];
        const double s_b = sb[p];

        for (uint32_t i = 0; i < NS; ++i) {
            const double ar = re[i];
            const double ai = im[i];
            const double ang = g * H[i] * TWO_PI;
            const double c = std::cos(ang);
            const double s = std::sin(ang);
            re[i] = ar * c - ai * s;
            im[i] = ar * s + ai * c;
        }

        for (uint32_t cq = 0; cq < NQ; ++cq) {
            for (uint32_t id2 = 0; id2 < (NS >> 1); ++id2) {
                const uint32_t a = swap_bits(id2 << 1, cq, 0);
                const uint32_t b = swap_bits((id2 << 1) | 1u, cq, 0);
                const double ar = re[a], ai = im[a];
                const double br = re[b], bi = im[b];
                re[a] = c_b * ar + s_b * bi;
                im[a] = c_b * ai - s_b * br;
                re[b] = s_b * ai + c_b * br;
                im[b] = -s_b * ar + c_b * bi;
            }
        }
    }

    const auto compute_t1 = std::chrono::steady_clock::now();
    const double compute_sec = std::chrono::duration<double>(compute_t1 - compute_t0).count();
    std::printf("qaoa_sim_compute_sec %.9g\n", compute_sec);
    std::fflush(stdout);

    std::ofstream out(output_path, std::ios::binary);
    if (!out) die("qaoa_sim: cannot open output file");
    out.write(reinterpret_cast<const char*>(re.data()), sizeof(double) * NS);
    out.write(reinterpret_cast<const char*>(im.data()), sizeof(double) * NS);
    if (!out) die("qaoa_sim: output write failed");

    FILE* fp = std::fopen(result_path, "w");
    if (!fp) die("qaoa_sim: cannot open result.txt");
    for (uint32_t i = 0; i < NS; ++i) write_hex_fixed(fp, re[i], 61);
    for (uint32_t i = 0; i < NS; ++i) write_hex_fixed(fp, im[i], 61);
    std::fclose(fp);

    fp = std::fopen("statistics.txt", "a");
    std::fprintf(fp, "cputime: %.9g\n", compute_sec);
    std::fclose(fp);
    return 0;
}
