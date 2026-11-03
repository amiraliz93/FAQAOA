# stats.py
import subprocess
import time

# arguments

for NQ in [4, 8, 10, 12, 14, 16]:
    for NP in range(1, 33):
        args = ["python3", "-m", "main.Test.q2test", "--NQ", str(NQ), "--Np", str(NP), "--niter", str(16)]
        print("running...", args)
        subprocess.run(args, capture_output=False, text=True)

    