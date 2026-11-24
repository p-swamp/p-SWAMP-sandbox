"""Power flow parameters, read straight from the CIM graph with LazyCIM queries.

A notebook in a plain file, as ``offline_run.py``: each ``# %%`` is a cell, and the whole file runs
top to bottom:

    uv run python scripts/power_flow.py

Every number comes from a ``repo.query(L.<Class>).to_dataframe(column=F.<path>, ...)``: the
equipment parameters from EQ (r, x, bch, ratedU, ...), the operating point from SSH (p, q, open,
step, sections, targetValue), and where everything connects from the Terminals. From those the
script builds what a load flow takes, all per unit on ``S_BASE``:

- ``bus``: one row per bus (ConnectivityNodes joined by closed switches), its type (slack / PV /
  PQ), net injection P, Q, and the voltage set point of its machines;
- ``branch``: one row per line and transformer, series r, x, charging b and the tap ratio;
- ``Y``: the bus admittance matrix, shunts included.

Then a plain Newton-Raphson solves it, and the result is compared with the solved state the
grid's SV profile holds.
"""

# %% Settings
import pswamp_proto  # first: it sets OPENBLAS_NUM_THREADS before numpy is imported

GRID = "./grids/nordic44"  # as in offline_run.py: "sample", "nordic44", a folder of CGMES files, ...
S_BASE = 1000.0  # MVA, the system base
SHUNT_G = False  # include the shunts' gPerSection: Nordic44's SV state was solved without it (~1 MW of losses)

# %% Load the grid (slow)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from lazycim import F, L  # noqa: E402
from scipy.sparse import coo_matrix  # noqa: E402
from scipy.sparse.csgraph import connected_components  # noqa: E402

repo = pswamp_proto.open_grid(GRID)

# %% Where everything connects: Terminals, and the ConnectivityNodes they sit on
# A Terminal joins one end of a piece of ConductingEquipment to a ConnectivityNode. `connected`
# (SSH) is False where the end is disconnected, as at both ends of an open switch.
terminals = repo.query(L.Terminal).to_dataframe(
    terminal=F.mRID,
    equipment=F.ConductingEquipment.mRID,
    node=F.ConnectivityNode.mRID,
    seq=F.sequenceNumber,
    connected=F.connected,
)
nodes = repo.query(L.ConnectivityNode).to_dataframe(
    node=F.mRID,
    name=F.name,
    kv=F.TopologicalNode.BaseVoltage.nominalVoltage,  # a ConnectivityNode has no voltage of its own
    tn=F.TopologicalNode.mRID,  # for comparing with SV at the end
)
nodes["name"] = nodes["name"].str.strip()
print(f"{len(terminals)} terminals on {len(nodes)} connectivity nodes")

# %% Topology: the buses are the ConnectivityNodes that closed switches join
switches = repo.query(L.Switch).to_dataframe(mrid=F.mRID, name=F.name, open=F.open)  # Breaker, Disconnector, ...
print(f"{len(switches)} switches, {switches['open'].sum()} open")

# A line with no impedance is a bus tie too: as a branch it would make Y infinite.
ties = repo.query(L.ACLineSegment).to_dataframe(mrid=F.mRID, r=F.r, x=F.x, in_service=F.inService)
ties = ties[(ties["r"] == 0) & (ties["x"] == 0) & ties["in_service"].astype(bool)]
print(f"{len(ties)} lines with no impedance, merged as closed switches")

node_idx = {mrid: i for i, mrid in enumerate(nodes["node"])}
closed = pd.concat([switches.loc[~switches["open"].astype(bool), "mrid"], ties["mrid"]])
joined = terminals[terminals["equipment"].isin(closed) & terminals["connected"]]
ends = joined.sort_values("seq").groupby("equipment")["node"].agg(list)
ends = ends[ends.str.len() == 2]  # both ends connected
a, b = zip(*((node_idx[n1], node_idx[n2]) for n1, n2 in ends))
_, node_bus = connected_components(coo_matrix((np.ones(len(a)), (a, b)), shape=(len(nodes),) * 2), directed=False)
nodes["bus"] = node_bus  # each ConnectivityNode's bus, numbered from 0

# A bus is named after its first ConnectivityNode, and has that node's nominal voltage.
buses = nodes.sort_values("name").groupby("bus").agg(name=("name", "first"), kv=("kv", "first")).sort_index()
print(f"{len(nodes)} connectivity nodes -> {len(buses)} buses (before dropping the dead ones)")


def at(equipment_mrids: pd.Series) -> pd.DataFrame:
    """For each piece of equipment, the bus of each of its ends (columns 1, 2, ...) and whether
    every end is connected."""
    t = terminals[terminals["equipment"].isin(equipment_mrids)].assign(bus=lambda d: d["node"].map(nodes.set_index("node")["bus"]))
    where = t.pivot(index="equipment", columns="seq", values="bus")
    where["connected"] = t.groupby("equipment")["connected"].all()
    return where


# %% Lines: ACLineSegment, r, x and bch (total) in ohm and siemens
lines = repo.query(L.ACLineSegment).to_dataframe(mrid=F.mRID, name=F.name, r=F.r, x=F.x, bch=F.bch, in_service=F.inService)
lines = lines[~lines["mrid"].isin(ties["mrid"])].reset_index(drop=True)  # the ties are in the buses already
lines = lines.join(at(lines["mrid"]), on="mrid")
z_base = buses["kv"].to_numpy(float) ** 2 / S_BASE  # ohm, per bus
zb = z_base[lines[1].to_numpy(int)]
line_branch = pd.DataFrame({
    "name": lines["name"],
    "kind": "line",
    "from": lines[1].to_numpy(int),
    "to": lines[2].to_numpy(int),
    "r": lines["r"] / zb,
    "x": lines["x"] / zb,
    "b": lines["bch"] * zb,  # total; half at each end
    "ratio": 1.0,
    "in_service": lines["in_service"].astype(bool) & lines["connected"],
})

# %% Transformers: PowerTransformer, its PowerTransformerEnds (windings) and their RatioTapChangers
transformers = repo.query(L.PowerTransformer).to_dataframe(mrid=F.mRID, name=F.name, in_service=F.inService)
windings = repo.query(L.PowerTransformerEnd).to_dataframe(
    end=F.mRID,
    transformer=F.PowerTransformer.mRID,
    number=F.endNumber,
    terminal=F.Terminal.mRID,
    r=F.r,  # ohm, referred to this winding's ratedU
    x=F.x,
    rated_u=F.ratedU,  # kV
    rated_s=F.ratedS,  # MVA
)
taps = repo.query(L.RatioTapChanger).to_dataframe(
    end=F.TransformerEnd.mRID,
    step=F.step,  # SSH: the position now
    neutral_step=F.neutralStep,
    increment=F.stepVoltageIncrement,  # % of neutralU per step
    neutral_u=F.neutralU,
)
windings = windings.merge(taps, on="end", how="left")
# The winding's voltage, moved off its rating by the tap position (ratedU where there is no tap changer).
windings["u"] = (windings["neutral_u"] * (1 + (windings["step"] - windings["neutral_step"]) * windings["increment"] / 100)).fillna(windings["rated_u"])
windings["bus"] = windings["terminal"].map(terminals.set_index("terminal")["node"]).map(nodes.set_index("node")["bus"])
windings["connected"] = windings["terminal"].map(terminals.set_index("terminal")["connected"])

w1 = windings[windings["number"] == 1].set_index("transformer")
w2 = windings[windings["number"] == 2].set_index("transformer")
assert windings.groupby("transformer").size().eq(2).all(), "only two-winding transformers here"
t1, t2 = w1.loc[transformers["mrid"]], w2.loc[transformers["mrid"]]
kv1 = buses["kv"].to_numpy(float)[t1["bus"].to_numpy(int)]
kv2 = buses["kv"].to_numpy(float)[t2["bus"].to_numpy(int)]
turns = (t1["rated_u"] / t2["rated_u"]).to_numpy() ** 2
zb = kv1**2 / S_BASE
trafo_branch = pd.DataFrame({
    "name": transformers["name"].to_numpy(),
    "kind": "transformer",
    "from": t1["bus"].to_numpy(int),
    "to": t2["bus"].to_numpy(int),
    "r": (t1["r"].to_numpy() + t2["r"].fillna(0).to_numpy() * turns) / zb,  # both windings, referred to winding 1
    "x": (t1["x"].to_numpy() + t2["x"].fillna(0).to_numpy() * turns) / zb,
    "b": 0.0,  # the magnetising b and g of the ends are left out
    "ratio": (t2["u"].to_numpy() / kv2) / (t1["u"].to_numpy() / kv1),  # off-nominal ratio, at the "from" end
    "in_service": transformers["in_service"].astype(bool).to_numpy() & t1["connected"].to_numpy() & t2["connected"].to_numpy(),
})

branch = pd.concat([line_branch, trafo_branch], ignore_index=True)
print(f"{len(lines)} lines and {len(transformers)} transformers, {(~branch['in_service']).sum()} out of service")

# %% Injections: loads, machines and shunts, each at the bus of its one terminal
loads = repo.query(L.EnergyConsumer).to_dataframe(mrid=F.mRID, name=F.name, p=F.p, q=F.q, in_service=F.inService)  # MW, Mvar drawn (SSH)
machines = repo.query(L.SynchronousMachine).to_dataframe(
    mrid=F.mRID,
    name=F.name,
    p=F.p,  # MW, SSH, load sign convention: negative is generation
    q=F.q,
    rated_s=F.ratedS,
    min_q=F.minQ,
    max_q=F.maxQ,
    target_kv=F.RegulatingControl.targetValue,  # the voltage it regulates to (here at its own terminal)
    in_service=F.inService,
)
shunts = repo.query(L.LinearShuntCompensator).to_dataframe(
    mrid=F.mRID, name=F.name, b=F.bPerSection, g=F.gPerSection, sections=F.sections, in_service=F.inService
)  # siemens per section; sections in use (SSH)

for table in (loads, machines, shunts):
    table[["bus", "connected"]] = at(table["mrid"]).loc[table["mrid"], [1, "connected"]].to_numpy()
    table["on"] = table["in_service"].astype(bool) & table["connected"].astype(bool)
    table["bus"] = table["bus"].astype(int)

# %% Drop what the slack bus cannot reach
# The slack bus: that of the largest machine (SynchronousMachine.referencePriority could say otherwise).
SLACK = int(machines.loc[machines["rated_s"].idxmax(), "bus"])
on = branch[branch["in_service"]]
n_all = len(buses)
_, island = connected_components(coo_matrix((np.ones(len(on)), (on["from"], on["to"])), shape=(n_all, n_all)), directed=False)
alive = np.flatnonzero(island == island[SLACK])
renumber = np.full(n_all, -1)
renumber[alive] = np.arange(len(alive))
print(f"{n_all - len(alive)} dead buses dropped: {list(buses['name'].to_numpy()[island != island[SLACK]])}")

buses = buses.iloc[alive].reset_index(drop=True)
n = len(buses)
branch = branch[branch["in_service"] & (renumber[branch["from"]] >= 0)].assign(
    **{"from": lambda d: renumber[d["from"]], "to": lambda d: renumber[d["to"]]}
).reset_index(drop=True)
branch.insert(2, "from_bus", buses["name"].to_numpy()[branch["from"]])
branch.insert(3, "to_bus", buses["name"].to_numpy()[branch["to"]])
for table in (loads, machines, shunts):
    table["bus"] = renumber[table["bus"]]
    table["on"] &= table["bus"] >= 0
loads, machines, shunts = (t[t["on"]].reset_index(drop=True) for t in (loads, machines, shunts))
SLACK = renumber[SLACK]
print(branch.to_string())

# %% The buses: type, net injection and voltage set point, per unit
kv = buses["kv"].to_numpy(float)
p_gen = np.bincount(machines["bus"], -machines["p"], n) / S_BASE
q_gen = np.bincount(machines["bus"], -machines["q"], n) / S_BASE  # what SSH says; a PV bus's Q is solved for
p_load = np.bincount(loads["bus"], loads["p"], n) / S_BASE
q_load = np.bincount(loads["bus"], loads["q"], n) / S_BASE

v_set = np.full(n, np.nan)
for b_, group in machines.groupby("bus"):
    if group["target_kv"].nunique() > 1:
        print(f"bus {buses['name'][b_]!r}: machines with different targets {sorted(group['target_kv'])} kV; using the first")
    v_set[b_] = group["target_kv"].iloc[0] / kv[b_]

bus = pd.DataFrame({
    "name": buses["name"],
    "kv": kv,
    "type": np.where(np.arange(n) == SLACK, "slack", np.where(np.isfinite(v_set), "PV", "PQ")),
    "P": p_gen - p_load,  # net injection, pu: specified at PV and PQ buses
    "Q": -q_load,  # net injection, pu: specified at PQ buses
    "V_set": v_set,  # pu: specified at PV and slack buses
    "Q_min": np.bincount(machines["bus"], machines["min_q"].fillna(-np.inf), n) / S_BASE,  # for limit checks
    "Q_max": np.bincount(machines["bus"], machines["max_q"].fillna(np.inf), n) / S_BASE,
})
print(bus.to_string())
print(f"generation {p_gen.sum() * S_BASE:.0f} MW scheduled (the slack bus's is solved for), load {p_load.sum() * S_BASE:.0f} MW")


# %% The bus admittance matrix
def admittance_matrix(branch: pd.DataFrame, y_shunt: np.ndarray) -> np.ndarray:
    """Y (pu) of the branches and the bus shunts. A transformer with off-nominal ratio a at its
    "from" end: Y_ff = a^2 y, Y_tt = y, Y_ft = Y_tf = -a y (as TOPS and LazyCIM model it)."""
    n = len(y_shunt)
    Y = np.diag(y_shunt.astype(complex))
    y = 1 / (branch["r"].to_numpy() + 1j * branch["x"].to_numpy())
    half_b = 0.5j * branch["b"].to_numpy()
    f, t, a = branch["from"].to_numpy(), branch["to"].to_numpy(), branch["ratio"].to_numpy()
    np.add.at(Y, (f, f), a**2 * y + half_b)
    np.add.at(Y, (t, t), y + half_b)
    np.add.at(Y, (f, t), -a * y)
    np.add.at(Y, (t, f), -a * y)
    return Y


# A shunt draws (g - jb) V^2: per unit on the bus's voltage, y = (g + jb) * sections * kV^2 / S_BASE.
y_shunt = np.bincount(shunts["bus"], (shunts["g"].fillna(0) * SHUNT_G * shunts["sections"] * kv[shunts["bus"]] ** 2), n) / S_BASE
y_shunt = y_shunt + 1j * np.bincount(shunts["bus"], (shunts["b"] * shunts["sections"] * kv[shunts["bus"]] ** 2), n) / S_BASE
Y = admittance_matrix(branch, y_shunt)
print(f"Y: {n} x {n}, {np.count_nonzero(Y)} non-zeros")


# %% A plain Newton-Raphson over bus and Y
def newton_raphson(Y, bus, tol=1e-8, max_it=20):
    """Bus voltages (complex, pu) solving the load flow of ``bus`` (its type, P, Q, V_set) over ``Y``."""
    kind = bus["type"].to_numpy()
    pv, pq = np.flatnonzero(kind == "PV"), np.flatnonzero(kind == "PQ")
    pvpq = np.r_[pv, pq]
    s_spec = bus["P"].to_numpy() + 1j * bus["Q"].to_numpy()
    v = np.where(np.isfinite(bus["V_set"]), bus["V_set"], 1.0).astype(complex)
    for it in range(max_it):
        mismatch = v * np.conj(Y @ v) - s_spec
        f = np.r_[mismatch.real[pvpq], mismatch.imag[pq]]
        if abs(f).max() < tol:
            return v, it
        # dS/dθ and dS/d|V|, the usual compact form
        i_bus = Y @ v
        dS_dth = 1j * np.diag(v) @ np.conj(np.diag(i_bus) - Y @ np.diag(v))
        dS_dvm = np.diag(v) @ np.conj(Y @ np.diag(v / abs(v))) + np.diag(v / abs(v)) @ np.diag(np.conj(i_bus))
        J = np.block([
            [dS_dth.real[np.ix_(pvpq, pvpq)], dS_dvm.real[np.ix_(pvpq, pq)]],
            [dS_dth.imag[np.ix_(pq, pvpq)], dS_dvm.imag[np.ix_(pq, pq)]],
        ])
        dx = np.linalg.solve(J, -f)
        theta, vm = np.angle(v), abs(v)
        theta[pvpq] += dx[: len(pvpq)]
        vm[pq] += dx[len(pvpq):]
        v = vm * np.exp(1j * theta)
    raise RuntimeError(f"no convergence in {max_it} iterations (largest mismatch {abs(f).max():.2e} pu)")


v, iterations = newton_raphson(Y, bus)
s = v * np.conj(Y @ v)
print(f"converged in {iterations} iterations; slack bus {bus['name'][SLACK]!r} gives {s[SLACK].real * S_BASE:.0f} MW, "
      f"losses {s.real.sum() * S_BASE:.1f} MW")
q_machines = s.imag + q_load  # what the machines of each bus give
over = (bus["type"] != "PQ") & ((q_machines < bus["Q_min"] - 1e-6) | (q_machines > bus["Q_max"] + 1e-6))
if over.any():
    print(f"machines past their Q limits (not enforced here): {list(bus['name'][over])}")

# %% Compare with the solved state the grid's SV profile holds (SvVoltage, per TopologicalNode)
result = bus[["name", "type", "kv"]].assign(V_pu=abs(v), angle_deg=np.degrees(np.angle(v)), P_pu=s.real, Q_pu=s.imag)
sv = repo.query(L.SvVoltage).to_dataframe(tn=F.TopologicalNode.mRID, v_sv=F.v, angle_sv=F.angle)
if len(sv):
    on_bus = nodes.assign(bus=renumber[nodes["bus"]]).query("bus >= 0").merge(sv, on="tn").query("v_sv > 0")
    on_bus = on_bus.groupby("bus")[["v_sv", "angle_sv"]].first()
    result["V_sv_pu"] = on_bus["v_sv"] / result["kv"]
    result["angle_sv_deg"] = on_bus["angle_sv"]
    print(f"largest difference from SV: |V| {(result['V_pu'] - result['V_sv_pu']).abs().max():.1e} pu, "
          f"angle {(result['angle_deg'] - result['angle_sv_deg']).abs().max():.1e} deg")
print(result.to_string(float_format="{:.4f}".format))

# %%
