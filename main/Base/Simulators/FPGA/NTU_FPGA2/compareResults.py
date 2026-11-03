# written by copilot, 2026 05 05

P = 64
N = 61
def hex_to_float(hex_str):
    # Convert hex string to integer
    b_unsigned = int(hex_str, 16)
    
    # Convert from unsigned to signed (two's complement)
    if b_unsigned >= (1 << (P - 1)):
        b_signed = b_unsigned - (1 << P)
    else:
        b_signed = b_unsigned
    
    # Convert to float
    return b_signed / float(1 << N)

def load_floats(filename):

    values = []
    with open(filename, "r") as f:
        for line in f:
            line = line.strip()
            if line:  # skip empty lines
                values.append(hex_to_float(line))
    return values


def mean_absolute_error(a, b):
    n = min(len(a), len(b))
    if n == 0:
        raise ValueError("No comparable data found")

    mae = sum(abs(a[i] - b[i]) for i in range(n)) / n
    return mae, n


if __name__ == "__main__":
    result_file = "result.txt"
    ref_file = "simulation/questa/result_sim1.txt"
    #ref_file = "resultFPGA.txt"

    result_values = load_floats(result_file)
    ref_values = load_floats(ref_file)

    mae = mean_absolute_error(result_values, ref_values)

    print(f"MAE = {mae}")