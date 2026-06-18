# PropellerLab UI 输入项定义说明

本文档说明 PropellerLab 桌面程序中各个 UI 输入项的含义、单位、默认值以及它们在计算中的作用。

适用项目目录：

```text
D:\CodexProjects\PropellerLab
```

对应主要代码文件：

```text
propeller_lab/ui/main_window.py
propeller_lab/core/models.py
propeller_lab/core/geometry.py
propeller_lab/core/bemt.py
```

## 1. 左侧输入面板

左侧输入面板分为四个区域：

- Geometry
- Operating point
- Model
- Actions

其中 Geometry、Operating point 和 Model 会形成一次螺旋桨计算的核心输入；Actions 是按钮操作。

## 2. Geometry 几何输入

### 2.1 Blades B

UI 名称：

```text
Blades B
```

代码控件：

```python
self.blades_spin = _spin_int(1, 12, 2)
```

含义：

叶片数量，记为 `B`。

默认值：

```text
2
```

输入范围：

```text
1 到 12
```

作用：

用于计算所有叶片合计的推力、扭矩和功率。单个叶素产生的升力、阻力会乘以叶片数 `B`，得到整副螺旋桨的局部载荷。

在 BEMT 中也用于 Prandtl 桨尖/桨毂损失因子计算。

### 2.2 Diameter D, m

UI 名称：

```text
Diameter D, m
```

代码控件：

```python
self.diameter_spin = _spin_float(0.001, 10.0, 0.254, 4, 0.001)
```

含义：

螺旋桨直径，记为 `D`，单位为米。

默认值：

```text
0.254 m
```

输入范围：

```text
0.001 m 到 10.0 m
```

作用：

半径由直径得到：

```text
R = D / 2
```

`R` 会用于：

- 生成径向叶素站位
- 将无量纲弦长 `chord_over_R` 转换为实际弦长
- 计算 CT、CQ、CP
- 判断桨尖位置和 Prandtl 损失

### 2.3 Hub diameter, m

UI 名称：

```text
Hub diameter, m
```

代码控件：

```python
self.hub_spin = _spin_float(0.0, 9.0, 0.035, 4, 0.001)
```

含义：

桨毂直径，单位为米。

默认值：

```text
0.035 m
```

输入范围：

```text
0.0 m 到 9.0 m
```

作用：

桨毂半径为：

```text
r_hub = hub_diameter_m / 2
```

默认自动几何生成时，叶素起点会避开桨毂区域：

```text
r_start = max(hub_diameter_m / 2, 0.20 * R)
```

在启用 hub loss 时，桨毂半径也用于 Prandtl root loss 计算。

### 2.4 Pitch P, m

UI 名称：

```text
Pitch P, m
```

代码控件：

```python
self.pitch_spin = _spin_float(0.0, 10.0, 0.1143, 4, 0.001)
```

含义：

几何桨距，记为 `P`，单位为米。

桨距可以理解为：如果螺旋桨像螺钉一样在理想无滑移状态下旋转一圈，理论上沿轴向前进的距离。

默认值：

```text
0.1143 m
```

输入范围：

```text
0.0 m 到 10.0 m
```

作用：

当没有导入真实几何 CSV 时，程序会用几何桨距自动生成每个径向站位的局部桨距角 `beta_deg`。

局部半径为 `r` 时：

```text
beta = atan(pitch_m / (2*pi*r))
beta_deg = degrees(beta)
```

注意：

`beta` 是角度，不是距离。

`r` 才是该叶素距离旋转中心轴的半径距离。

同一个桨距 `P` 下：

- 靠近桨根，`r` 较小，`beta` 较大
- 靠近桨尖，`r` 较大，`beta` 较小

### 2.5 Root chord c_root/R

UI 名称：

```text
Root chord c_root/R
```

代码控件：

```python
self.root_chord_spin = _spin_float(0.001, 1.0, 0.16, 4, 0.001)
```

含义：

根部弦长与螺旋桨半径的比值。

默认值：

```text
0.16
```

输入范围：

```text
0.001 到 1.0
```

作用：

自动生成几何时，靠近根部的弦长由该值决定。

实际弦长：

```text
chord_m = chord_over_R * R
```

### 2.6 Tip chord c_tip/R

UI 名称：

```text
Tip chord c_tip/R
```

代码控件：

```python
self.tip_chord_spin = _spin_float(0.001, 1.0, 0.06, 4, 0.001)
```

含义：

桨尖弦长与螺旋桨半径的比值。

默认值：

```text
0.06
```

输入范围：

```text
0.001 到 1.0
```

作用：

自动生成几何时，桨尖附近的弦长由该值决定。

程序会在根部弦长比和桨尖弦长比之间做线性插值，生成每个径向站位的 `chord_over_R`。

### 2.7 Elements

UI 名称：

```text
Elements
```

代码控件：

```python
self.elements_spin = _spin_int(3, 500, 50)
```

含义：

径向叶素数量。

默认值：

```text
50
```

输入范围：

```text
3 到 500
```

作用：

决定沿半径方向将螺旋桨叶片分成多少个计算站位。

叶素越多，径向积分越细，但计算量也越大。

程序要求计算结果中的 station 数量等于 `elements`。

## 3. Operating point 工况输入

### 3.1 RPM

UI 名称：

```text
RPM
```

代码控件：

```python
self.rpm_spin = _spin_float(0.0, 200000.0, 8000.0, 1, 100.0)
```

含义：

螺旋桨转速，单位为转每分钟。

默认值：

```text
8000 RPM
```

输入范围：

```text
0 到 200000 RPM
```

作用：

程序内部会转换为：

```text
n = RPM / 60
omega = 2*pi*n
```

其中：

- `n` 是每秒转数
- `omega` 是角速度，单位 rad/s

`RPM` 会直接影响局部切向速度：

```text
wt = omega * r
```

也会影响推力、扭矩、功率、CT、CQ、CP。

### 3.2 Freestream velocity V_inf, m/s

UI 名称：

```text
Freestream velocity V_inf, m/s
```

代码控件：

```python
self.vinf_spin = _spin_float(0.0, 400.0, 0.0, 3, 0.1)
```

含义：

来流速度，记为 `V_inf`，单位为 m/s。

默认值：

```text
0.0 m/s
```

输入范围：

```text
0.0 到 400.0 m/s
```

作用：

表示螺旋桨轴向迎风速度。

在静拉力计算中：

```text
V_inf = 0
```

在前飞计算中：

```text
V_inf > 0
```

在 Auto solver 模式中，程序会根据 `V_inf`、`J` 和 `mu_adv` 判断是否使用低速维度 BEMT。

### 3.3 Density rho

UI 名称：

```text
Density rho
```

代码控件：

```python
self.rho_spin = _spin_float(0.001, 50.0, 1.225, 4, 0.001)
```

含义：

流体密度，记为 `rho`，单位通常为 kg/m^3。

默认值：

```text
1.225
```

输入范围：

```text
0.001 到 50.0
```

作用：

用于计算动压、雷诺数、动量理论推力和无量纲系数。

动压：

```text
q = 0.5 * rho * W^2
```

雷诺数：

```text
Re = rho * W * chord / mu
```

### 3.4 Dynamic viscosity mu

UI 名称：

```text
Dynamic viscosity mu
```

代码控件：

```python
self.mu_spin = _spin_float(0.00000001, 0.1, 1.81e-5, 8, 0.000001)
```

含义：

动力粘度，记为 `mu`。

默认值：

```text
1.81e-5
```

输入范围：

```text
1e-8 到 0.1
```

作用：

用于计算局部雷诺数：

```text
Re = rho * W * chord / mu
```

雷诺数会传给 airfoil polar 查表或简化翼型模型，用于产生低雷诺数 warning。

### 3.5 Sound speed a

UI 名称：

```text
Sound speed a
```

代码控件：

```python
self.sound_speed_spin = _spin_float(1.0, 2000.0, 343.0, 3, 1.0)
```

含义：

声速，记为 `a`，单位为 m/s。

默认值：

```text
343.0 m/s
```

输入范围：

```text
1.0 到 2000.0 m/s
```

作用：

用于计算局部 Mach 数：

```text
Mach = W / sound_speed
```

当 Mach 较高时，程序会给出高 Mach warning。

## 4. Model 模型输入

### 4.1 Calculation mode

UI 名称：

```text
Calculation mode
```

代码选项：

```python
self.calc_mode_combo.addItem("Auto solver", "auto")
self.calc_mode_combo.addItem("Simple blade element", "simple")
self.calc_mode_combo.addItem("Simple blade element + axial induction", "simple_induced")
self.calc_mode_combo.addItem("Forward-flight phi-BEMT", "bemt_phi_forward")
self.calc_mode_combo.addItem("Dimensional low-speed BEMT", "bemt_hover_dimensional")
```

默认选项：

```text
Auto solver
```

作用：

选择核心计算器使用哪种叶素/BEMT 求解模式。

#### Auto solver

自动选择求解器。

程序根据以下指标判断：

```text
n = rpm / 60
R = diameter / 2
omega = 2*pi*n
J = V_inf / (n*D)
mu_adv = V_inf / (omega*R)
```

如果满足低速条件，使用：

```text
bemt_hover_dimensional
```

否则使用：

```text
bemt_phi_forward
```

#### Simple blade element

简化叶素法，不考虑诱导速度。

局部轴向速度：

```text
wa = V_inf
```

局部切向速度：

```text
wt = omega * r
```

适合快速估算，但静拉力和低速时通常不够稳健。

#### Simple blade element + axial induction

简化诱导速度模型。

程序会用局部动量近似迭代轴向诱导速度 `vi`。

如果局部推力为负，程序会将诱导速度设为 0，并给出 warning。

#### Forward-flight phi-BEMT

前飞 phi-BEMT。

该方法求解入流角 `phi`，并使用轴向诱导因子 `a` 和切向诱导因子 `a_prime`。

适合非低速前飞工况。

在 `V_inf` 接近 0 时，`a = vi / V_inf` 容易退化，因此程序会自动替换为低速维度 BEMT，并给出 warning。

#### Dimensional low-speed BEMT

低速/静拉力维度 BEMT。

该方法直接求解轴向诱导速度：

```text
vi, m/s
```

不会使用：

```text
a = vi / V_inf
```

因此适合 `V_inf = 0` 或接近 0 的工况。

### 4.2 Polar mode

UI 名称：

```text
Polar mode
```

代码选项：

```python
self.polar_mode_combo.addItem("Generic airfoil", "generic")
self.polar_mode_combo.addItem("Imported polar CSV", "table")
self.polar_mode_combo.addItem("XFOIL cached polar", "xfoil_cached")
```

默认选项：

```text
Generic airfoil
```

作用：

选择翼型气动数据来源。

#### Generic airfoil

使用程序内置简化翼型模型。

适合没有 polar 数据时的快速估算。

#### Imported polar CSV

使用用户导入的 polar CSV。

CSV 至少应包含：

```text
alpha_deg,cl,cd,cm
```

程序会按 `alpha_deg` 线性插值。

#### XFOIL cached polar

使用 XFOIL 页生成并导入到当前程序缓存的 polar 数据。

注意：

计算过程中不会实时调用 XFOIL；XFOIL 只用于预先生成 polar。

### 4.3 Use tip loss

UI 名称：

```text
Use tip loss
```

代码控件：

```python
self.tip_loss_check = QCheckBox("Use tip loss")
self.tip_loss_check.setChecked(True)
```

含义：

是否启用 Prandtl 桨尖损失修正。

默认值：

```text
启用
```

作用：

启用后，靠近桨尖的有效载荷会受到损失因子 `F` 修正。

### 4.4 Use hub loss

UI 名称：

```text
Use hub loss
```

代码控件：

```python
self.hub_loss_check = QCheckBox("Use hub loss")
self.hub_loss_check.setChecked(True)
```

含义：

是否启用 Prandtl 桨毂/根部损失修正。

默认值：

```text
启用
```

作用：

启用后，靠近桨毂的有效载荷会受到损失因子 `F` 修正。

## 5. Actions 操作按钮

### 5.1 Calculate

执行一次螺旋桨计算。

程序会读取当前 Geometry、Operating point、Model 输入，然后调用：

```python
calculate_propeller(...)
```

计算完成后刷新：

- Summary
- Radial loads 图
- Aero state 图
- Station table

### 5.2 Import geometry CSV

导入自定义几何 CSV。

CSV 格式：

```text
r_over_R,chord_over_R,beta_deg,airfoil_id
```

导入后，当前计算使用导入几何，而不是根据 pitch 自动生成几何。

### 5.3 Export geometry CSV

导出当前几何 CSV。

如果已经导入过几何，则导出导入几何。

如果没有导入几何，则根据当前 UI 参数自动生成几何后导出。

### 5.4 Import polar CSV

导入翼型 polar CSV。

导入成功后，Polar mode 会切换为：

```text
Imported polar CSV
```

### 5.5 Export station CSV

导出径向站点计算结果。

包括：

- r/R
- r_m
- dr_m
- chord_m
- beta_deg
- phi_deg
- alpha_deg
- Reynolds
- Mach
- Cl
- Cd
- Cm
- vi_mps
- vt_mps
- F
- dT/dr
- dQ/dr
- warning

### 5.6 Export summary CSV

导出总性能结果、输入参数、diagnostics 和 warnings。

包括：

- T
- Q
- P
- eta
- CT
- CQ
- CP
- requested_mode
- actual_mode
- J
- mu_adv
- max_alpha_deg
- stall_station_fraction
- low_re_station_fraction
- negative_thrust_station_fraction
- max_vi_mps
- solver_fallback_fraction

## 6. RPM sweep 输入

RPM sweep 位于右侧 Tab：

```text
RPM sweep
```

该页会复用左侧当前输入，只改变 RPM。

### 6.1 rpm_start

代码控件：

```python
self.rpm_start_spin = _spin_float(0.0, 200000.0, 4000.0, 1, 100.0)
```

含义：

RPM 扫描起点。

默认值：

```text
4000 RPM
```

范围：

```text
0 到 200000 RPM
```

### 6.2 rpm_end

代码控件：

```python
self.rpm_end_spin = _spin_float(0.0, 200000.0, 12000.0, 1, 100.0)
```

含义：

RPM 扫描终点。

默认值：

```text
12000 RPM
```

范围：

```text
0 到 200000 RPM
```

要求：

```text
rpm_end >= rpm_start
```

### 6.3 rpm_step

代码控件：

```python
self.rpm_step_spin = _spin_float(1.0, 100000.0, 1000.0, 1, 100.0)
```

含义：

RPM 扫描步长。

默认值：

```text
1000 RPM
```

范围：

```text
1 到 100000 RPM
```

作用：

程序从 `rpm_start` 开始，每次增加 `rpm_step`，直到 `rpm_end`。

### 6.4 Start sweep

开始 RPM 扫描。

每个 RPM 点都会调用一次核心计算。

输出表格包含：

- RPM
- T
- Q
- P
- eta
- CT
- CQ
- CP
- warnings_count

### 6.5 Export sweep CSV

导出 RPM 扫描结果 CSV。

## 7. XFOIL polar generator 输入

XFOIL 页用于调用外部 XFOIL 程序生成翼型 polar。

注意：

XFOIL 不是实时 BEMT 求解的一部分。它只用于提前生成 polar 数据。

### 7.1 XFOIL executable path

代码控件：

```python
self.xfoil_path_edit = QLineEdit("xfoil")
```

含义：

XFOIL 可执行文件路径。

默认值：

```text
xfoil
```

如果系统 PATH 中有 XFOIL，保持默认即可。

如果没有，需要选择具体的 `xfoil.exe` 路径。

### 7.2 Browse

选择 XFOIL 可执行文件路径。

### 7.3 Check XFOIL

检查 XFOIL 是否能启动。

如果找不到 XFOIL，只影响 XFOIL 页，不影响普通螺旋桨计算。

### 7.4 Airfoil source

代码选项：

```python
self.airfoil_source_combo.addItem("NACA")
self.airfoil_source_combo.addItem("DAT file")
```

含义：

选择翼型来源。

#### NACA

使用 NACA 四位数翼型编号，例如：

```text
4412
```

#### DAT file

使用翼型坐标 DAT 文件。

### 7.5 NACA code

代码控件：

```python
self.naca_edit = QLineEdit("4412")
```

含义：

NACA 四位数翼型编号。

默认值：

```text
4412
```

仅当 Airfoil source 为 `NACA` 时使用。

### 7.6 DAT file path

代码控件：

```python
self.dat_path_edit = QLineEdit()
```

含义：

翼型 DAT 坐标文件路径。

仅当 Airfoil source 为 `DAT file` 时使用。

### 7.7 DAT Browse

选择 DAT 文件路径。

### 7.8 Reynolds

代码控件：

```python
self.xfoil_re_spin = _spin_float(1000.0, 50000000.0, 100000.0, 0, 1000.0)
```

含义：

XFOIL 计算 polar 时使用的 Reynolds 数。

默认值：

```text
100000
```

范围：

```text
1000 到 50000000
```

### 7.9 Mach

代码控件：

```python
self.xfoil_mach_spin = _spin_float(0.0, 2.0, 0.0, 3, 0.01)
```

含义：

XFOIL 计算 polar 时使用的 Mach 数。

默认值：

```text
0.0
```

范围：

```text
0.0 到 2.0
```

### 7.10 alpha_start

代码控件：

```python
self.alpha_start_spin = _spin_float(-90.0, 90.0, -10.0, 2, 0.5)
```

含义：

XFOIL 攻角扫描起点，单位 deg。

默认值：

```text
-10 deg
```

范围：

```text
-90 deg 到 90 deg
```

### 7.11 alpha_end

代码控件：

```python
self.alpha_end_spin = _spin_float(-90.0, 90.0, 15.0, 2, 0.5)
```

含义：

XFOIL 攻角扫描终点，单位 deg。

默认值：

```text
15 deg
```

范围：

```text
-90 deg 到 90 deg
```

### 7.12 alpha_step

代码控件：

```python
self.alpha_step_spin = _spin_float(0.01, 20.0, 0.5, 2, 0.1)
```

含义：

XFOIL 攻角扫描步长，单位 deg。

默认值：

```text
0.5 deg
```

范围：

```text
0.01 deg 到 20.0 deg
```

### 7.13 ITER

代码控件：

```python
self.iter_spin = _spin_int(1, 1000, 100)
```

含义：

XFOIL 每个攻角点的最大迭代次数。

默认值：

```text
100
```

范围：

```text
1 到 1000
```

作用：

较大的 ITER 可能提高收敛机会，但会增加运行时间。

### 7.14 panels

代码控件：

```python
self.panels_spin = _spin_int(20, 500, 160)
```

含义：

XFOIL 面元数量。

默认值：

```text
160
```

范围：

```text
20 到 500
```

作用：

影响 XFOIL 对翼型几何的离散精度。

### 7.15 timeout

代码控件：

```python
self.timeout_spin = _spin_float(1.0, 600.0, 60.0, 1, 1.0)
```

含义：

XFOIL 子进程超时时间，单位秒。

默认值：

```text
60 s
```

范围：

```text
1 s 到 600 s
```

作用：

防止 XFOIL 不收敛或卡住时阻塞程序。

### 7.16 Run XFOIL

启动 XFOIL polar 计算。

该操作在后台线程中运行，不会阻塞主 UI。

### 7.17 Save polar CSV

保存 XFOIL 生成的 polar CSV。

导出的 CSV 可被 TablePolar 读取。

### 7.18 Use as current polar

将 XFOIL 生成的 polar 数据作为当前计算使用的 polar。

要求：

```text
XFOIL 结果至少包含 5 个数据点
```

否则程序不会允许导入为当前 polar。

## 8. Summary 中的 diagnostics 字段说明

虽然 diagnostics 显示在 Summary 页，但它们不是用户输入，而是程序根据输入和计算结果生成的诊断值。

### requested_mode

用户在 Calculation mode 中请求的模式。

### actual_mode

程序实际使用的求解模式。

例如用户选择 Auto solver 时，实际模式可能是：

```text
bemt_hover_dimensional
```

或：

```text
bemt_phi_forward
```

### J

前进比：

```text
J = V_inf / (n * D)
```

### mu_adv

推进速度比：

```text
mu_adv = V_inf / (omega * R)
```

### max_alpha_deg

所有径向站位中最大绝对攻角，单位 deg。

### stall_station_fraction

可能处于失速攻角范围的站位比例。

### low_re_station_fraction

低 Reynolds 数站位比例。

### negative_thrust_station_fraction

局部推力为负的站位比例。

### max_vi_mps

最大轴向诱导速度，单位 m/s。

### solver_fallback_fraction

发生求解 fallback 的站位比例。

## 9. 输入之间的关键关系

### 9.1 pitch_m 与 beta_deg

`pitch_m` 是全局几何桨距，`beta_deg` 是某个半径位置的局部桨距角。

程序根据 `pitch_m` 和局部半径 `r` 生成：

```text
beta = atan(pitch_m / (2*pi*r))
```

因此 `beta_deg` 随半径变化。

### 9.2 rpm 与局部速度

RPM 决定角速度：

```text
omega = 2*pi*RPM/60
```

局部切向速度：

```text
wt = omega*r
```

半径越大，切向速度越大。

### 9.3 V_inf 与低速求解器

当 `V_inf` 很小或为 0 时，Auto solver 会选择低速维度 BEMT。

这样可以避免传统 forward-flight phi-BEMT 中：

```text
a = vi / V_inf
```

在静拉力下退化。

### 9.4 rho 与 mu 对 Reynolds 数的影响

雷诺数：

```text
Re = rho * W * chord / mu
```

密度越大，Re 越大。

粘度越大，Re 越小。

### 9.5 sound_speed 对 Mach 数的影响

Mach 数：

```text
Mach = W / sound_speed
```

声速设置越低，同样局部速度下 Mach 越高。

## 10. 常用默认输入汇总

| 输入项 | 默认值 |
|---|---:|
| Blades B | 2 |
| Diameter D, m | 0.254 |
| Hub diameter, m | 0.035 |
| Pitch P, m | 0.1143 |
| Root chord c_root/R | 0.16 |
| Tip chord c_tip/R | 0.06 |
| Elements | 50 |
| RPM | 8000 |
| V_inf, m/s | 0.0 |
| rho | 1.225 |
| mu | 1.81e-5 |
| Sound speed a | 343.0 |
| Calculation mode | Auto solver |
| Polar mode | Generic airfoil |
| Use tip loss | enabled |
| Use hub loss | enabled |

