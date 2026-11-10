# stats_experiment.py - runs qaoa_experiment.py in loops, like stats.py.
# Edit the settings below, then run:  python stats_experiment.py
import subprocess
import sys
import time

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
QAOA_EXPERIMENT = PROJECT_ROOT / "qaoa_experiment.py"
SHOW_RESULTS = PROJECT_ROOT / "experiment_simple" / "show_results.py"



datetime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
PORT = "COM6"
NOTE = f"FTDI latency timer 1 ms; board <TR5-5SGXEABN3F4513YY>; bitstream GOLDEN_TOP; run at {datetime}"
SIM = 'fpga'  # 'fpga' or 'sim'
AER_DEVICE = "CPU"




RUN_TIMING = False       # random problem: counter and transfer time for every size
RUN_MAXCUT = True      # Max-Cut graphs: FPGA vs C++ accuracy
RUN_OPTIMISE = False    # COBYLA with the FPGA in the loop
FAST_IO = True         # True: faster transfer (same commands, sent in blocks); check it on the board first

# Max-Cut graph used by RUN_MAXCUT and RUN_OPTIMISE
GRAPH = ["--graph", "regular", "--degree", "3", "--graph-seed", "1"]   # or "complete", "erdos", "file"


jobs = [] 

                                       # each job = the options for one qaoa_experiment.py run
if RUN_TIMING:                                   # about 2.5 h with the 1 ms latency timer
    for NQ in range(17, 18):                      # every size once, 1 layer
        jobs.append(["--mode", "random", "--NQ", NQ, "--Np", 1])
    #for NQ in [10, 14 ]:                           # 5 repeats: spread of the transfer time
    #   for NP in [2, 8, 16, 32]:                 # 1 layer, 2 layers, 3 layers, 4 layers
     #      jobs.append(["--mode", "random", "--NQ", NQ, "--Np", NP, "--repeats", 5])
    #jobs.append(["--mode", "random", "--NQ", 16, "--Np", 1, "--repeats", 4])   # 5 runs at n = 16 in total
    #jobs.append(["--mode", "random", "--NQ", 16, "--Np", 32])                  # the 111.6 ms point again

if RUN_MAXCUT:                                   # about 1.5 h
    for NQ in [17, 18]:
        for NP in [1]:
            jobs.append(["--mode", "graph", *GRAPH, "--NQ", NQ, "--Np", NP])


if RUN_OPTIMISE:
    for NQ in [8, 10, 12]:
        for NP in [1, 2, 3]:
            for seed in range(1, 5):
                jobs.append(["--mode", "graph", *GRAPH, "--NQ", NQ, "--Np", NP,
                             "--optimise", "--budget", 100, "--seed", seed])


t0 = time.time()
if SIM == 'aer':
    jobs = [j + ["--sim", "aer", "--device", AER_DEVICE] + ([] if "--optimise" in j else ["--repeats", 5]) for j in jobs if 'graph' in j]
failed = []
for k, job in enumerate(jobs, 1):
    print(f"\n##### run {k} of {len(jobs)}   (elapsed {(time.time() - t0) / 60:.0f} min)")
    cmd = [   sys.executable, str(QAOA_EXPERIMENT), "--port", PORT, "--note", NOTE,
                                                            ] + [str(a) for a in job]
    if FAST_IO:
        cmd.append("--fast-io")
    if subprocess.run(cmd).returncode != 0:
        failed.append(" ".join(str(a) for a in job))

print(f"\n##### finished {len(jobs)} runs in {(time.time() - t0) / 60:.0f} min")
for f in failed:
    print("FAILED:", f)
subprocess.run([sys.executable, str(SHOW_RESULTS), "--today"])      # summary tables, 5