import sys
print(sys.executable)
print(sys.path)
import numpy as np
from itertools import combinations
import scipy
import networkx as nx
import matplotlib.pyplot as plt


port = None
NQ, Np = 6, 2
head = ""
dic = {
    "--Np": 2,
    "--NQ": 6,
    "--port": "",
    "--sim": "cpp",
    "--output-sim": "",
    "--niter": 8
}
for i in range(1, len(sys.argv)):
    v = sys.argv[i]
    if head != "":
        dic[head] = type(dic[head])(v)
        head = ""
    if v in dic:
        head = v 
print(dic)
NQ = dic["--NQ"]
Np = dic["--Np"]
port = dic["--port"]
sim = dic["--sim"]
niter = dic["--niter"]
output_sim = dic["--output-sim"]

repo_root = r"C:\home\QAOAHP"
sys.path.insert(0, repo_root)
#sys.path.insert(0, r'C:\Users\N1259534\OneDrive - Nottingham Trent University\Desktop\Projects\QAOA_simulation_LV\QAOA_mtrix_simulation')
print(sys.executable)

from main.Base import choose_simulator
from main.QAOA_objective import get_qaoa_objective 
from scipy.optimize import minimize
np.random.seed(10)
G_simple2 = nx.Graph()
for i in range(NQ):
    for j in range(i+1, NQ):
        G_simple2.add_edge(i, j, weight=1.0)
theta0 = []
for i in range(Np*2):
    theta0.append(i/Np*0.5)

obj = get_qaoa_objective(G=G_simple2, simulator="qiskit")

result = minimize(obj, x0=theta0, method="COBYLA", options={'maxiter': niter})
print(result.x)
print(result.fun)