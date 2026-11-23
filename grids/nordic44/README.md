<!-- SPDX-License-Identifier: CC-BY-NC-SA-4.0 -->

# Nordic44 grid model (p-SWAMP derivative)

The CIM/CGMES model of the grid that the p-SWAMP grid monitor and the real-time
simulation run on. It is a **derivative of the Statnett
[Nordic44](https://github.com/statnett/Nordic44) model**, adapted for the
[p-SWAMP](../../README.md) platform (Power Stability Wide area Monitoring and
Protection), a SINTEF research project building on NEWEPS.

## License: not Apache-2.0

This folder is **not** covered by the Apache License 2.0 of the rest of the
repository. Nordic44 is published under the
[Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International](https://creativecommons.org/licenses/by-nc-sa/4.0/)
license (SPDX: `CC-BY-NC-SA-4.0`). Its ShareAlike term requires that adapted
material is distributed under the same license, so this derivative stays
under CC BY-NC-SA 4.0 too:

- The full text is in [`LICENSE`](LICENSE), copied from the upstream repository.
- Every `Nordic44-HV_*.xml` file carries `SPDX-License-Identifier: CC-BY-NC-SA-4.0`
  in a leading XML comment.
- Everything outside this folder is Apache-2.0, see the [root `LICENSE`](../../LICENSE).

What that means in practice:

- **Non-commercial only.** The model files, and copies of them, may not be used
  for commercial purposes. That includes shipping them inside a commercial
  product or service. The Apache-2.0 code of p-SWAMP can be used commercially,
  but not together with these files.
- **Attribution and share-alike.** Keep the notices in this folder when you
  redistribute, and distribute any further adaptation under CC BY-NC-SA 4.0 (or
  a compatible license).
- Releases, container images and packages built from this repository must not
  silently bundle this folder under an "Apache-2.0" label. Mention the exception,
  or leave the folder out.

## Attribution

Original work: **Nordic44**, Statnett SF, <https://github.com/statnett/Nordic44>,
licensed under CC BY-NC-SA 4.0. The first released version is described in:

> L. Vanfretti, S.H. Olsen, V.S. Narasimham Arava, G. Laera, A. Bidadfar,
> T. Rabuzin, S. H. Jakobsen, J. Lavenius, M. Baudette and F.J. Gómez-López,
> "An Open Data Repository and a Data Processing Software Toolset of an
> Equivalent Nordic Grid Model Matched to Historical Electricity Market Data",
> *Data in Brief* (Elsevier), 17 February 2017,
> [doi:10.1016/j.dib.2017.02.021](http://dx.doi.org/10.1016/j.dib.2017.02.021).

The original PSS/E-based model was provided by Emil Hillberg at STRI. Please
credit the original authors when you use or redistribute this model.

## Changes made to the original

Compared object by object (CIM `rdf:ID` and properties, not text) against upstream
`main` at commit [`74e66ad`](https://github.com/statnett/Nordic44/commit/74e66ad3c5de0b318cc7f8c72478b685e00fde4c)
(2026-05-15), and, for the dynamics profile, against the upstream branch
`79-add-dynamic-dy-model` at `39b2b59`. Only the CIM/XML `Grid` instance is
used; the other upstream formats and instances are not included.

| File | Change against upstream |
|---|---|
| `_EQ` | Unchanged: 2154 objects, identical content. |
| `_TP` | Unchanged: 492 objects, identical content. |
| `_SSH` | Changed operating point: `RotatingMachine.p` and `.q` differ on all 80 `SynchronousMachine` objects. Everything else is identical. |
| `_SV` | Changed state: `SvVoltage.v` and `.angle` differ on 45 nodes, `SvPowerFlow.p` and `.q` on 243 flows. No objects added or removed. |
| `_GL` | Extended: 57 `Location` objects added, for the 45 `VoltageLevel` and 12 `PowerTransformer` objects that had none, and the `PositionPoint` objects were regenerated (184 removed, 426 added). The 112 original `Location` objects are kept. The model header is now version 2 and supersedes the upstream one. |
| `_OP` | Replaced: the 176 upstream objects are removed. The file now holds 1102 `Analog` and 55 `Discrete` measurements, each with a value object, and two `MeasurementValueSource` objects (`SCADA`, `PMU`). The measurement types are active and reactive power, phase angle, current magnitude, line-to-line voltage, frequency, rate of change of frequency and switch position. |
| `_DY` | Added. Upstream has no `_DY` on `main`, and the branch above holds a partial draft (61 machine reactance objects, 34 `GovHydro1`, 9 `ExcSEXS`). This file has 80 each of `SynchronousMachineTimeConstantReactance`, `ExcSEXS`, `GovSteam0` and `PssIEEE1A`, one set per `SynchronousMachine`. It has its own identifiers and nothing is taken over from the upstream draft. |
| `_DL` | Not included. Upstream has a diagram-layout profile, and the SVG diagrams, `manifest` files and JSON-LD and TriG renderings are not carried over. |

Other changes, applied to all seven XML files:

- Added an `SPDX-License-Identifier: CC-BY-NC-SA-4.0` comment after the XML
  declaration. The XML content is otherwise untouched by that step.
- Added this `README.md` and `LICENSE`.


## Files

| File | CGMES profile |
|---|---|
| `Nordic44-HV_EQ.xml` | Equipment |
| `Nordic44-HV_TP.xml` | Topology |
| `Nordic44-HV_SSH.xml` | Steady-state hypothesis |
| `Nordic44-HV_SV.xml` | State variables |
| `Nordic44-HV_GL.xml` | Geographical location |
| `Nordic44-HV_DY.xml` | Dynamics (added, not in upstream `main`) |
| `Nordic44-HV_OP.xml` | Operation (SCADA and PMU measurements) |
