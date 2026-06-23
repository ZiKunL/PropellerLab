# PropellerLab UI 输入项定义说明

本文档说明 PropellerLab 桌面程序中各个 UI 输入项的含义、单位、默认值以及它们在计算中的作用。

适用项目目录：

```text
D:\CodexProjects\PropellerLab
```

对应主要代码文件：

```text
propeller_lab/ui/main_window.py
propeller_lab/ui/app_state.py
propeller_lab/ui/optimization_worker.py
propeller_lab/ui/plot_widgets.py
propeller_lab/core/models.py
propeller_lab/core/geometry.py
propeller_lab/core/bemt.py
propeller_lab/core/design.py
propeller_lab/core/optimizer.py
propeller_lab/core/export.py
propeller_lab/core/storage.py
propeller_lab/core/xfoil_runner.py
```

## 0. Workspace 工作区选择

主窗口顶部有工作区选择器：

```text
Workspace:
```

当前包含三个工作区：

- `Base Calculate`
- `Optimization Design`
- `Target Optimization`

### 0.1 Base Calculate

基础计算工作区。

包含：

- 左侧 Geometry、Operating point、Model、Actions 输入面板
- Summary
- Radial loads
- Aero state
- Station table
- RPM sweep
- XFOIL polar generator

用途：

用于直接分析当前螺旋桨几何、工况和 polar 数据，计算推力、扭矩、功率、效率和径向站位结果。

### 0.2 Optimization Design

早期扭转设计工作区。

用途：

根据当前工况、polar 和设计目标生成新的 twist/beta 分布，并可把生成几何应用回 `Base Calculate`。

### 0.3 Target Optimization

目标优化工作区。

用途：

根据目标推力或目标扭矩，在给定直径、转速、弦长范围、beta 范围和优化器设置下搜索较优的弦长分布和扭转分布。

注意：

`Target Optimization` 是基于当前 BEMT 模型和 polar 数据的工程搜索，不是 CFD，不是结构优化，也不保证真实全局最优。

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

### 2.4 Pitch input

UI 名称：

```text
Pitch input
```

代码控件：

```python
self.pitch_input_combo = QComboBox()
self.pitch_input_combo.addItem("Pitch P, m", "pitch")
self.pitch_input_combo.addItem("Pitch angle at 70%R, deg", "pitch_angle")
```

含义：

选择桨距输入方式。

当前支持两种互斥输入：

- `Pitch P, m`：直接输入几何桨距，单位 m
- `Pitch angle at 70%R, deg`：输入展向 70% 半径处的桨距角，单位 deg

默认值：

```text
Pitch P, m
```

作用：

该选项保证 `Pitch P, m` 和 `Pitch angle at 70%R, deg` 二选一生效。

当选择 `Pitch P, m` 时，Pitch 输入框可编辑，Pitch angle 输入框只显示换算结果。

当选择 `Pitch angle at 70%R, deg` 时，Pitch angle 输入框可编辑，程序会自动换算出 Pitch，并显示在 Pitch 输入框中。

### 2.5 Pitch P, m

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

### 2.6 Pitch angle at 70%R, deg

UI 名称：

```text
Pitch angle at 70%R, deg
```

代码控件：

```python
self.pitch_angle_spin = _spin_float(0.0, 89.0, 11.568, 3, 0.1)
```

含义：

展向 70% 半径位置处的局部桨距角，单位 deg。

这里的 70% 半径位置是：

```text
r_ref = 0.70 * R
```

其中：

```text
R = D / 2
```

默认值：

```text
11.568 deg
```

输入范围：

```text
0.0 deg 到 89.0 deg
```

作用：

当 Pitch input 选择 `Pitch angle at 70%R, deg` 时，程序用该角度反算几何桨距：

```text
Pitch = 2*pi*(0.70*R)*tan(Pitch_angle)
```

然后现有几何生成仍然使用换算出的 `pitch_m`，所以不会和原来的 Pitch 工作流冲突。

注意：

该角度是 70% 半径处的局部桨距角，不是所有半径位置的统一安装角。

其他半径位置的 `beta_deg` 仍会根据换算出的 Pitch 和当地半径 `r` 重新计算。

### 2.7 Root chord c_root/R

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

### 2.8 Tip chord c_tip/R

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

### 2.9 Elements

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
self.xfoil_path_edit = QLineEdit(_default_xfoil_path())
```

含义：

XFOIL 可执行文件路径。

默认值：

```text
优先使用项目本地 tools/xfoil/xfoil-6.99/xfoil.exe；
如果该文件不存在，则显示 xfoil。
```

当前本地推荐路径：

```text
D:\CodexProjects\PropellerLab\tools\xfoil\xfoil-6.99\xfoil.exe
```

如果系统 PATH 中有 XFOIL，也可以保持：

```text
xfoil
```

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

选择 `NACA` 时：

- `NACA code` 可编辑
- `DAT file path` 锁定
- `DAT Browse` 锁定

#### DAT file

使用翼型坐标 DAT 文件。

选择 `DAT file` 时：

- `NACA code` 锁定
- `DAT file path` 可编辑
- `DAT Browse` 可用

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

默认文件名规则：

```text
{airfoil_name}_Re{reynolds}.csv
```

示例：

```text
naca4412_Re100000.csv
clark_y_Re152346.csv
```

说明：

- 当 Airfoil source 为 `NACA` 时，`airfoil_name` 来自 NACA code，例如 `naca4412`
- 当 Airfoil source 为 `DAT file` 时，`airfoil_name` 来自 DAT 文件名，例如 `Clark Y.dat` 会变成 `clark_y`
- Reynolds 数优先使用当前显示的 XFOIL 表对应的 Reynolds
- 如果当前没有可识别的显示表 Reynolds，则使用 `Reynolds` 输入框中的数值
- 文件名会自动转成适合文件系统使用的 ASCII token

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

如果使用 `Pitch angle at 70%R, deg` 输入，程序会先按 70% 半径位置反算 `pitch_m`：

```text
pitch_m = 2*pi*(0.70*R)*tan(pitch_angle_deg)
```

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
| Pitch input | Pitch P, m |
| Pitch P, m | 0.1143 |
| Pitch angle at 70%R, deg | 11.568 |
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

## 11. Reynolds 范围估算与 XFOIL 多雷诺数扫描

本节说明本次新增的 XFOIL 辅助输入。它们位于右侧 `XFOIL polar generator` 页面，用于根据当前螺旋桨几何和工况自动估计翼型 polar 需要覆盖的 Reynolds 数范围。

### 11.1 Auto Re range

UI 名称：
```text
Auto Re range
```

含义：
是否自动根据当前输入刷新 `Re min`、`Re max` 和单点 `Reynolds`。

默认状态：
```text
enabled
```

触发条件：
当以下输入变化时，程序会静默重新估算 Reynolds 范围：
- Diameter D, m
- Hub diameter, m
- Pitch P, m
- Pitch angle at 70%R, deg
- Root chord c_root/R
- Tip chord c_tip/R
- Elements
- RPM
- Freestream velocity V_inf, m/s
- Density rho
- Dynamic viscosity mu
- Re count

估算公式：
```text
omega = 2*pi*RPM/60
W = sqrt(V_inf^2 + (omega*r)^2)
chord = chord_over_R * R
Re = rho * W * chord / mu
```

程序会沿当前叶素站位计算每个站位的 `Re`，然后取最小值作为 `Re min`，最大值作为 `Re max`。

### 11.2 Estimate Re range

UI 名称：
```text
Estimate Re range
```

含义：
手动执行一次 Reynolds 范围估算。

作用：
点击后会：
- 根据当前几何和工况刷新 `Re min`、`Re max`
- 根据 `Re count` 生成若干代表性 Reynolds 数
- 把代表性 Reynolds 数写入 XFOIL 日志
- 自动勾选 `Use multi-Re sweep`

### 11.3 Use multi-Re sweep

UI 名称：
```text
Use multi-Re sweep
```

含义：
控制 XFOIL 是只计算一个 Reynolds，还是在 `Re min` 到 `Re max` 之间计算多个 Reynolds。

未勾选时：
```text
XFOIL 只使用 Reynolds 输入框中的单个 Re 值。
```

勾选时：
```text
XFOIL 会根据 Re min、Re max 和 Re count 生成多个 Re 值，并分别运行 polar 扫描。
```

### 11.4 Re min

UI 名称：
```text
Re min
```

含义：
XFOIL 多 Reynolds 扫描的下限。

来源：
通常由 `Auto Re range` 或 `Estimate Re range` 自动填入，也可以手动修改。

### 11.5 Re max

UI 名称：
```text
Re max
```

含义：
XFOIL 多 Reynolds 扫描的上限。

来源：
通常由 `Auto Re range` 或 `Estimate Re range` 自动填入，也可以手动修改。

### 11.6 Re count

UI 名称：
```text
Re count
```

含义：
在 `Re min` 到 `Re max` 范围内选取多少个代表性 Reynolds 数用于 XFOIL 计算。

默认值：
```text
3
```

范围：
```text
1 到 7
```

取值规则：
如果 `Re max / Re min` 较大，程序使用近似对数分布，避免低 Reynolds 区域采样过少；如果范围较窄，则使用线性分布。

### 11.7 多 Reynolds polar 在 BEMT 中如何使用

当 `Use multi-Re sweep` 启用并且 XFOIL 成功生成至少两个可用 Reynolds 表后，点击：
```text
Use as current polar
```

程序会把这些表组合为 `MultiRePolar`。后续 BEMT 计算每个叶素站位时，会把该站位自己的 Reynolds 数传给 polar 查询函数：
```text
Cl, Cd, Cm = polar.lookup(alpha, station_Re, station_Mach)
```

因此，计算不会只使用单一 Reynolds 表，而是在 XFOIL 生成的多个 Reynolds 表之间插值。这样对于根部、桨尖和中间展向位置 Reynolds 差异较大的螺旋桨，会比单 Re polar 更贴近真实工况。

## 12. Optimization Design 工作区输入

`Optimization Design` 是扭转设计工作区，用于根据当前工况和 polar 生成新的 beta/twist 分布。

它不是完整的全局优化器，主要用于早期设计和快速生成可分析的桨叶扭转。

### 12.1 Design method

UI 名称：

```text
Design method
```

选项：

```text
Max Cl/Cd Twist Design
Target Thrust Twist Design
Target Power Twist Design
```

含义：

选择设计模式。

- `Max Cl/Cd Twist Design`：按选定 alpha 目标生成扭转，不追踪总推力或总功率目标
- `Target Thrust Twist Design`：在生成扭转后允许通过 beta offset 接近目标推力
- `Target Power Twist Design`：在生成扭转后允许通过 beta offset 接近目标功率

UI 锁定规则：

- 当前 `Target type` 会自动跟随 `Design method`
- `Target type` 本身不可手动编辑
- 只有目标推力或目标功率模式下，`Target value` 和 `Allow beta offset` 才可用

### 12.2 Design RPM

UI 名称：

```text
Design RPM
```

含义：

设计工况转速，单位 RPM。

默认值：

启动时复制 Base Calculate 中的 `RPM`。

作用：

用于设计时估算局部速度、Reynolds、Mach 和入流角。

### 12.3 Design V_inf, m/s

UI 名称：

```text
Design V_inf, m/s
```

含义：

设计工况来流速度，单位 m/s。

默认值：

启动时复制 Base Calculate 中的 `Freestream velocity V_inf, m/s`。

作用：

用于设计时估算前飞或静拉力工况下的局部入流。

### 12.4 Target type

UI 名称：

```text
Target type
```

选项：

```text
None
Target thrust
Target power
```

含义：

设计目标类型。

注意：

该控件由 `Design method` 自动同步，当前 UI 中处于锁定状态，用户通过 `Design method` 间接选择。

### 12.5 Target value

UI 名称：

```text
Target value
```

含义：

目标数值。

单位由 `Target type` 决定：

- `Target thrust`：单位 N
- `Target power`：单位 W
- `None`：不使用

UI 锁定规则：

只有 `Target Thrust Twist Design` 或 `Target Power Twist Design` 模式下可编辑。

### 12.6 Alpha objective

UI 名称：

```text
Alpha objective
```

选项：

```text
Max Cl/Cd
Max local thrust/torque ratio
Fixed alpha
```

含义：

选择每个径向站位的设计攻角选取方式。

- `Max Cl/Cd`：在 alpha 扫描范围内选择升阻比最高的攻角
- `Max local thrust/torque ratio`：在 alpha 扫描范围内选择局部推力/扭矩贡献较优的攻角
- `Fixed alpha`：直接使用固定攻角

### 12.7 Fixed alpha, deg

UI 名称：

```text
Fixed alpha, deg
```

含义：

固定设计攻角，单位 deg。

UI 锁定规则：

只有 `Alpha objective` 为 `Fixed alpha` 时可编辑。

注意：

固定攻角不再被 `Alpha min` 和 `Alpha max` 限制，但仍会被程序内部基本有限值检查保护。

### 12.8 Alpha min, deg

UI 名称：

```text
Alpha min, deg
```

含义：

alpha 扫描范围下限，单位 deg。

UI 锁定规则：

当 `Alpha objective` 为 `Fixed alpha` 时锁定；其他 alpha 目标下可编辑。

### 12.9 Alpha max, deg

UI 名称：

```text
Alpha max, deg
```

含义：

alpha 扫描范围上限，单位 deg。

UI 锁定规则：

当 `Alpha objective` 为 `Fixed alpha` 时锁定；其他 alpha 目标下可编辑。

### 12.10 Alpha step, deg

UI 名称：

```text
Alpha step, deg
```

含义：

alpha 扫描步长，单位 deg。

作用：

步长越小，搜索更细，但计算量更大。

### 12.11 Stall margin, deg

UI 名称：

```text
Stall margin, deg
```

含义：

选择 `Max Cl/Cd` 时用于避开接近失速区域的安全裕度，单位 deg。

UI 锁定规则：

仅 `Alpha objective` 为 `Max Cl/Cd` 时可编辑。

### 12.12 Max Cl fraction

UI 名称：

```text
Max Cl fraction
```

含义：

选择 `Max Cl/Cd` 时允许使用的最大升力系数比例。

作用：

避免设计攻角贴近最大 Cl 或失速边界。

UI 锁定规则：

仅 `Alpha objective` 为 `Max Cl/Cd` 时可编辑。

### 12.13 Beta min, deg

UI 名称：

```text
Beta min, deg
```

含义：

设计生成 beta 的下限，单位 deg。

### 12.14 Beta max, deg

UI 名称：

```text
Beta max, deg
```

含义：

设计生成 beta 的上限，单位 deg。

### 12.15 Max tip Mach

UI 名称：

```text
Max tip Mach
```

含义：

设计允许的最大桨尖 Mach 数。

作用：

如果工况导致桨尖 Mach 超过该值，设计结果会产生 warning 或诊断提示。

### 12.16 Chord mode

UI 名称：

```text
Chord mode
```

选项：

```text
Keep current chord
Linear chord
```

含义：

控制设计时弦长分布如何生成。

- `Keep current chord`：尽量保留当前几何或 Base Calculate 自动生成的弦长分布
- `Linear chord`：使用线性弦长分布

### 12.17 Allow beta offset

UI 名称：

```text
Allow beta offset
```

含义：

是否允许程序对整条桨叶 beta 分布施加统一偏移，以接近目标推力或目标功率。

UI 锁定规则：

只有目标推力或目标功率模式下可用。

### 12.18 Generate design

生成设计几何。

输出会刷新：

- Design summary
- Design station table
- Design plots

### 12.19 Analyze generated design

使用当前设计几何重新运行一次 Base Calculate 核心求解器。

作用：

用于验证设计几何在当前设置下的推力、扭矩、功率和效率。

### 12.20 Apply to Base Calculate

把设计生成的几何设置为 Base Calculate 的当前自定义几何。

执行后：

- `current_geometry` 被替换为设计几何
- `Elements` 更新为设计几何站位数
- 自动刷新 Reynolds 范围
- 切换回 `Base Calculate`
- 自动运行一次计算

### 12.21 Export designed geometry CSV

导出设计生成的几何 CSV。

格式：

```text
r_over_R,chord_over_R,beta_deg,airfoil_id
```

### 12.22 Export design station CSV

导出设计站位表。

包含：

- r/R
- chord/R
- phi_deg
- alpha_design_deg
- beta_deg
- Re
- Mach
- Cl
- Cd
- Cl/Cd
- objective_value
- warning

## 13. Target Optimization 工作区输入

`Target Optimization` 是目标驱动的几何优化工作区。

它会优化：

- chord/R 控制点
- beta_deg 控制点

然后把控制点插值成完整径向几何，并调用现有 `calculate_propeller` 对每个候选几何进行分析。

重要原则：

- 优化循环中不调用 XFOIL
- 只使用当前已有的 GenericPolar、Imported polar、XFOIL cached polar 或 MultiRePolar
- 输出的是模型搜索结果，不是 CFD、结构优化或真实全局最优

### 13.1 Target mode

UI 名称：

```text
Target mode
```

选项：

```text
Target thrust, minimize power
Target thrust with torque limit
Target torque, maximize thrust
Match thrust
Match torque
```

含义：

选择优化目标。

- `Target thrust, minimize power`：匹配目标推力，同时倾向较低功率
- `Target thrust with torque limit`：匹配目标推力，并惩罚超过扭矩限制的候选
- `Target torque, maximize thrust`：把目标扭矩作为限制，尽量提高推力
- `Match thrust`：主要匹配目标推力，不强调功率最小
- `Match torque`：主要匹配目标扭矩；注意这只是负载匹配，不代表效率最优

UI 锁定规则：

- 目标推力相关模式启用 `Target thrust, N`
- 目标扭矩相关模式启用 `Target torque, N*m`
- 扭矩限制相关模式启用 `Torque limit, N*m`

### 13.2 Target thrust, N

UI 名称：

```text
Target thrust, N
```

含义：

目标推力，单位 N。

用于：

- `Target thrust, minimize power`
- `Target thrust with torque limit`
- `Match thrust`

### 13.3 Target torque, N*m

UI 名称：

```text
Target torque, N*m
```

含义：

目标扭矩，单位 N*m。

用于：

- `Target torque, maximize thrust`
- `Match torque`

### 13.4 Torque limit, N*m

UI 名称：

```text
Torque limit, N*m
```

含义：

扭矩上限，单位 N*m。

用于：

- `Target thrust with torque limit`
- `Target torque, maximize thrust`

注意：

在 `Target torque, maximize thrust` 中，`Target torque, N*m` 本身也会被当作主要扭矩限制。

### 13.5 Power limit, W

UI 名称：

```text
Power limit, W
```

含义：

功率上限，单位 W。

默认值：

```text
0
```

作用：

当大于 0 时，候选几何如果超过该功率，会在 fitness 中受到额外惩罚。

### 13.6 Blades B

含义：

目标优化使用的叶片数。

作用与 Base Calculate 中 `Blades B` 相同。

### 13.7 Diameter D, m

含义：

目标优化使用的参考螺旋桨直径，单位 m。

当 `Diameter min D, m` 与 `Diameter max D, m` 相等时，优化使用固定直径。

当 `Diameter min D, m` 小于 `Diameter max D, m` 时，优化器会把直径 D 也作为一个优化变量，在该范围内搜索最佳直径。

要求：

```text
Diameter D, m > Hub diameter, m
```

### 13.8 Diameter min D, m

含义：

目标优化允许搜索的最小螺旋桨直径，单位 m。

要求：

```text
Diameter min D, m > Hub diameter, m
Diameter min D, m <= Diameter max D, m
```

作用：

决定优化器可选直径范围下限。Reynolds 范围估算、几何站位半径、BEMT 分析都会覆盖该直径范围。

### 13.9 Diameter max D, m

含义：

目标优化允许搜索的最大螺旋桨直径，单位 m。

作用：

决定优化器可选直径范围上限。优化完成后，summary 中的 `best diameter D, m` 表示最终选中的直径。

### 13.10 Hub diameter, m

含义：

目标优化使用的桨毂直径，单位 m。

作用：

决定优化几何控制点和站位起点，起点通常不小于：

```text
max(hub_radius/R, 0.20)
```

### 13.11 RPM

含义：

目标优化固定转速，单位 RPM。

注意：

当前 MVP 优化固定 RPM，不同时优化转速。

### 13.12 V_inf, m/s

含义：

目标优化设计来流速度，单位 m/s。

可以为 0，用于静拉力或近静拉力优化。

### 13.13 Density rho

含义：

目标优化使用的流体密度。

### 13.14 Dynamic viscosity mu

含义：

目标优化使用的动力粘度。

### 13.13 Sound speed a

含义：

目标优化使用的声速，单位 m/s。

用于计算站位 Mach 数和相关惩罚。

### 13.14 Elements

含义：

目标优化生成的径向站位数量。

作用：

优化器不会直接优化每个站位，而是优化少量控制点，再插值生成 `Elements` 个站位。

### 13.15 Polar source display

UI 显示示例：

```text
Polar: Generic airfoil
Polar: current table with N point(s)
Polar: current Multi-Re table
Polar: target XFOIL multi-airfoil (N airfoil(s))
Polar: missing; optimizer will use Generic airfoil
```

含义：

显示 Target Optimization 当前会使用的 polar 数据来源。

规则：

- 如果 Base Calculate 的 `Polar mode` 为 `Generic airfoil`，优化使用 GenericPolar
- 如果当前存在 Imported polar 或 XFOIL cached polar，优化直接使用该 polar 对象
- 如果已经通过 Target Optimization 中的 `Build target XFOIL polars` 生成多翼型 polar，优化优先使用该多翼型 polar
- 如果 UI 选择了 imported/XFOIL 模式但没有可用 polar，优化会回退到 GenericPolar，并在日志中提示

多翼型逻辑：

当 Target Optimization 几何站位包含 `airfoil_id` 时，如果当前 polar 是 `MultiAirfoilPolar`，BEMT 会按站位的 `airfoil_id` 选择对应翼型 polar，再按该站位 Reynolds 插值。

### 13.16 Use Base Calculate inputs

UI 名称：

```text
Use Base Calculate inputs
```

作用：

把 Base Calculate 中的主要几何和工况输入复制到 Target Optimization：

- Blades
- Diameter
- Hub diameter
- RPM
- V_inf
- rho
- mu
- Sound speed
- Elements

如果 Base Calculate 已经有计算结果，还会把当前 T、Q、P 作为目标值或限制的参考初值。

### 13.17 Use current Base polar

UI 名称：

```text
Use current Base polar
```

作用：

刷新 Target Optimization 中的 polar 来源显示。

注意：

该按钮不重新运行 XFOIL，也不导入新文件，只读取当前 AppState 中的 polar 状态。

### 13.17.1 Airfoil optimization mode

UI 名称：

```text
Airfoil optimization mode
```

选项：

```text
Hybrid root-to-tip
Compare uniform airfoils
```

含义：

定义 `NACA airfoils` 和/或 `DAT files` 中多个翼型的使用方式。

- `Hybrid root-to-tip`：混合翼型设计。列表按从桨根到桨尖解释，优化得到的一支桨会沿展向分配多个 `airfoil_id`
- `Compare uniform airfoils`：单翼型候选对比。NACA 列表和 DAT 文件列表会合并成候选集合，每个候选都会单独优化一支“全展向同翼型”的螺旋桨，然后在 `Airfoil comparison` 表中排名

示例：

```text
4412, 4612, 0012
```

在 `Hybrid root-to-tip` 下表示：

```text
根部 naca4412，中部 naca4612，尖部 naca0012
```

在 `Compare uniform airfoils` 下表示：

```text
分别优化全展向 naca4412、全展向 naca4612、全展向 naca0012 三支螺旋桨
```

注意：

对比模式下可以同时输入 NACA 编号和 DAT 文件，例如：

```text
NACA airfoils: 4412, 4612
DAT files:
D:\airfoils\Clark Y.dat
```

这会分别优化全展向 `naca4412`、全展向 `naca4612`、全展向 `clark_y` 三支螺旋桨。

对比模式下如果输入多个翼型，必须先点击 `Build target XFOIL polars` 生成包含这些翼型的 `MultiAirfoilPolar`。否则各翼型没有独立 polar 数据，程序会阻止启动优化。

### 13.17.2 Airfoil source

UI 名称：

```text
Airfoil source
```

选项：

```text
NACA list
DAT files
NACA + DAT candidates
```

含义：

选择 Target Optimization 多翼型 XFOIL 预处理的翼型来源。

- `NACA list`：用户输入多个 NACA 编号
- `DAT files`：用户输入或浏览选择多个翼型坐标 DAT 文件
- `NACA + DAT candidates`：仅在 `Compare uniform airfoils` 模式下使用，把 NACA 编号和 DAT 文件合并为候选集合

UI 锁定规则：

- 选择 `NACA list` 时，`NACA airfoils` 可编辑，`DAT files` 和 `Browse DAT files` 锁定
- 选择 `DAT files` 时，`DAT files` 和 `Browse DAT files` 可用，`NACA airfoils` 锁定
- 选择 `Compare uniform airfoils` 时，程序会自动切换为 `NACA + DAT candidates`，`NACA airfoils`、`DAT files` 和 `Browse DAT files` 都可用，`Airfoil source` 本身锁定

### 13.17.3 NACA airfoils

UI 名称：

```text
NACA airfoils
```

含义：

输入一个或多个 NACA 翼型编号。

解释方式由 `Airfoil optimization mode` 决定：

- `Hybrid root-to-tip`：按从桨根到桨尖的顺序排列
- `Compare uniform airfoils`：作为多个单翼型螺旋桨的候选集合，并可与 `DAT files` 中的候选一起比较

示例：

```text
4412, 2412, 0012
```

程序会规范化为：

```text
naca4412
naca2412
naca0012
```

作用：

在混合模式下，Target Optimization 生成几何时，会按展向把这些翼型分配给不同径向站位的 `airfoil_id`。例如三个翼型会大致分成根部、中部、尖部三个区域。

在对比模式下，程序会为每个翼型分别运行一次优化。每次优化内部都使用单个 `airfoil_id`，也就是整支桨都使用同一个翼型。

如果对比模式下同时填写了 DAT 文件，NACA 候选会排在 DAT 候选之前一起参与比较。

注意：

该输入本身只定义几何站位的翼型 ID。要让不同翼型真正使用不同 polar，需要点击 `Build target XFOIL polars` 生成多翼型 polar，或者手动提供支持多翼型的 polar 对象。

### 13.17.4 DAT files

UI 名称：

```text
DAT files
```

含义：

输入一个或多个翼型坐标 DAT 文件路径，每行一个。

解释方式由 `Airfoil optimization mode` 决定：

- `Hybrid root-to-tip`：按桨根到桨尖顺序排列
- `Compare uniform airfoils`：每个 DAT 文件是一种单翼型螺旋桨候选，并可与 `NACA airfoils` 中的候选一起比较

示例：

```text
D:\airfoils\root.dat
D:\airfoils\mid.dat
D:\airfoils\tip.dat
```

程序会使用 DAT 文件名作为 `airfoil_id`：

```text
Clark Y.dat -> clark_y
tip-airfoil.dat -> tip-airfoil
```

作用：

在混合模式下，Target Optimization 生成几何时，会把这些 DAT 文件对应的 `airfoil_id` 按展向分配给不同站位。

在对比模式下，程序会分别优化整支桨都使用某一个 DAT 翼型的候选结果。

点击 `Build target XFOIL polars` 后，程序会对每个 DAT 文件和每个代表性 Reynolds 值分别调用 XFOIL。

### 13.17.5 Browse DAT files

UI 名称：

```text
Browse DAT files
```

作用：

一次选择多个 DAT 文件，并把路径按选择顺序写入 `DAT files`。

注意：

混合模式下，文件顺序就是 root-to-tip 顺序。如果选择顺序不符合实际桨叶展向分布，需要手动调整多行文本顺序。对比模式下，顺序只影响候选运行顺序，不影响每支候选桨的展向分布。

### 13.17.6 Target Re min

UI 名称：

```text
Target Re min
```

含义：

Target Optimization 多翼型 XFOIL 预计算使用的 Reynolds 下限。

来源：

通常由 `Estimate optimization Re` 或 `Build target XFOIL polars` 根据优化范围自动计算。

### 13.17.7 Target Re max

UI 名称：

```text
Target Re max
```

含义：

Target Optimization 多翼型 XFOIL 预计算使用的 Reynolds 上限。

计算依据：

程序根据优化输入中的：

- Diameter
- Hub diameter
- RPM
- V_inf
- rho
- mu
- Elements
- Chord min c/R
- Chord max c/R

估算所有可能站位的 Reynolds 范围。

估算公式：

```text
omega = 2*pi*RPM/60
W = sqrt(V_inf^2 + (omega*r)^2)
chord = chord_over_R * R
Re = rho * W * chord / mu
```

其中 `chord_over_R` 会同时取 `Chord min c/R` 和 `Chord max c/R`，因此这是基于优化搜索范围的 Reynolds 覆盖估计，而不是只基于某一条固定几何。

### 13.17.8 Target Re count

UI 名称：

```text
Target Re count
```

含义：

在 `Target Re min` 到 `Target Re max` 之间选择多少个代表性 Reynolds 值用于每个翼型的 XFOIL 计算。

范围：

```text
1 到 7
```

作用：

每个选定 NACA 翼型都会在这些 Reynolds 值下生成一组 polar。后续优化时，各站位按自己的 Reynolds 在这些表之间插值。

对于 DAT 模式，每个选定 DAT 文件也会在这些 Reynolds 值下生成一组 polar。

### 13.17.9 Estimate optimization Re

UI 名称：

```text
Estimate optimization Re
```

作用：

根据当前 Target Optimization 的几何范围和工况，估算多翼型 XFOIL 需要覆盖的 Reynolds 范围，并刷新：

- Target Re min
- Target Re max

同时在优化日志中写入代表性 Reynolds 值。

### 13.17.10 Build target XFOIL polars

UI 名称：

```text
Build target XFOIL polars
```

作用：

为当前 airfoil source 中列出的每个翼型，在 `Target Re min` 到 `Target Re max` 的代表性 Reynolds 值上运行 XFOIL，生成多翼型、多 Reynolds polar。

来源为 `NACA list` 时：

```text
调用 XFOIL NACA 命令生成翼型。
```

来源为 `DAT files` 时：

```text
调用 XFOIL LOAD 命令读取 DAT 坐标文件。
```

来源为 `NACA + DAT candidates` 时：

```text
NACA 候选调用 XFOIL NACA 命令。
DAT 候选调用 XFOIL LOAD 命令。
所有成功结果合并成同一个 MultiAirfoilPolar。
```

生成结果：

```text
MultiAirfoilPolar
```

其中每个翼型内部可能是：

- `TablePolar`：只有一个 Reynolds 表
- `MultiRePolar`：有多个 Reynolds 表，可按站位 Re 插值

该按钮会使用 XFOIL 页中的设置：

- XFOIL executable path
- Mach
- alpha_start
- alpha_end
- alpha_step
- ITER
- panels
- timeout

重要说明：

XFOIL 只在点击该按钮时预计算 polar。正式 Target Optimization 候选评估过程中不会调用 XFOIL，只会使用已经生成的表格按 `airfoil_id` 和 Reynolds 进行插值。

### 13.17.11 Target airfoil polar status

UI 显示示例：

```text
Target airfoil polar: not built
Target airfoil polar: building
Target airfoil polar: 3 airfoil(s), 3 Re value(s)
Target airfoil polar: failed
```

含义：

显示 Target Optimization 专用多翼型 polar 的生成状态。

### 13.18 Control points

UI 名称：

```text
Control points
```

含义：

优化器沿展向使用的控制点数量。

作用：

Genome 长度为：

```text
2 * control_points
```

其中：

- 前半部分是 chord/R 控制点
- 后半部分是 beta_deg 控制点

控制点数量越多，几何自由度越高，但优化更难、更慢。

### 13.19 Chord min c/R

UI 名称：

```text
Chord min c/R
```

含义：

优化允许的最小无量纲弦长。

要求：

```text
Chord min c/R < Chord max c/R
```

### 13.20 Chord max c/R

UI 名称：

```text
Chord max c/R
```

含义：

优化允许的最大无量纲弦长。

### 13.21 Beta min, deg

UI 名称：

```text
Beta min, deg
```

含义：

优化允许的最小 beta 角，单位 deg。

要求：

```text
Beta min, deg < Beta max, deg
```

### 13.22 Beta max, deg

UI 名称：

```text
Beta max, deg
```

含义：

优化允许的最大 beta 角，单位 deg。

### 13.23 Max tip Mach

UI 名称：

```text
Max tip Mach
```

含义：

允许的最大 Mach 数约束。

作用：

如果候选几何的最大 Mach 超过该值，会增加 fitness 惩罚。

### 13.24 Max alpha, deg

UI 名称：

```text
Max alpha, deg
```

含义：

允许的最大绝对攻角参考值，单位 deg。

作用：

优化器用它判断 stall_fraction：

```text
stall_fraction = fraction(abs(alpha_deg) > Max alpha)
```

### 13.25 Max stall fraction

UI 名称：

```text
Max stall fraction
```

含义：

允许的高攻角/可能失速站位比例。

如果候选结果超过该比例，会增加 fitness 惩罚。

### 13.26 Max low Re fraction

UI 名称：

```text
Max low Re fraction
```

含义：

允许的低 Reynolds 站位比例。

程序默认把低于约 50000 的站位计入 low-Re 诊断。

### 13.27 Method

UI 名称：

```text
Method
```

选项：

```text
Genetic algorithm
Random search
GA + local refine
```

含义：

选择优化算法。

- `Random search`：每代随机采样候选
- `Genetic algorithm`：使用选择、交叉、变异和精英保留
- `GA + local refine`：先运行 GA，再围绕最优解做小范围坐标搜索

### 13.28 Population size

含义：

每代候选几何数量。

值越大，搜索更充分，但计算更慢。

### 13.29 Generations

含义：

优化代数。

总候选评估数量大约为：

```text
Population size * Generations
```

`GA + local refine` 会额外增加少量局部搜索评估。

### 13.30 Mutation rate

含义：

遗传算法中每个基因发生变异的概率。

过低可能陷入局部最优；过高可能导致搜索不稳定。

### 13.31 Crossover rate

含义：

遗传算法中两个父代进行交叉生成子代的概率。

### 13.32 Elitism count

含义：

每代直接保留到下一代的最优候选数量。

作用：

避免当前最优解因随机交叉或变异丢失。

### 13.33 Tournament size

含义：

遗传算法锦标赛选择的候选数量。

值越大，选择压力越强。

### 13.34 Random seed

含义：

随机种子。

作用：

相同输入和相同 seed 通常可以复现实验结果。

特殊值：

```text
0
```

在当前 UI 中表示不固定随机种子，即传入 `None`。

### 13.35 Smoothness weight

含义：

几何平滑性惩罚权重。

作用：

惩罚 chord 和 beta 的尖锐二阶变化，减少不合理振荡。

### 13.36 Power weight

含义：

功率相关惩罚权重。

作用：

在目标推力最小功率或功率限制场景中影响 fitness。

### 13.37 Torque weight

含义：

扭矩限制惩罚权重。

作用：

候选扭矩超过限制时，权重越高，惩罚越强。

### 13.38 Constraint weight

含义：

综合约束惩罚权重。

作用：

UI 中该值会映射到 Mach、stall、low-Re 和几何惩罚相关权重。

### 13.39 Start optimization

启动目标优化。

执行后：

- Start 按钮锁定
- Stop 按钮启用
- 后台 `OptimizationWorker` 在线程中运行
- 每代进度会刷新 history table、收敛图和当前 best geometry 图

### 13.40 Stop

请求停止优化。

注意：

停止不是强制杀线程，而是让优化器在下一个安全检查点返回当前 best-so-far 结果。

### 13.41 Apply best to Base Calculate

把优化得到的 best geometry 应用回 Base Calculate。

执行后：

- `AppState.current_geometry` 替换为 best geometry
- Base Calculate 的部分工况输入同步为优化输入
- 自动刷新 Auto Re range
- 切换到 `Base Calculate`
- 自动运行一次计算

### 13.42 Export best geometry CSV

导出最优几何 CSV。

格式：

```text
r_over_R,chord_over_R,beta_deg,airfoil_id
```

### 13.43 Export history CSV

导出优化历史 CSV。

包含：

- generation
- evaluations
- best_fitness
- best_thrust_N
- best_torque_Nm
- best_power_W
- best_eta
- best_ct
- best_cq
- best_cp
- target_error_fraction
- stall_fraction
- low_re_fraction
- max_mach

### 13.44 Export summary CSV

导出优化摘要 CSV。

包含：

- TargetOptimizationInput 输入参数
- best performance
- best_fitness
- target_error_fraction
- evaluations
- diagnostics
- warnings

### 13.45 Target Optimization 输出字段

Best result labels 包括：

- Best fitness
- Target error
- T, N
- Q, N*m
- P, W
- eta
- CT
- CQ
- CP
- best diameter D, m
- max alpha
- max Mach
- stall fraction
- low Re fraction
- evaluations
- warnings

这些字段用于判断最优候选是否真正满足目标，而不是只看推力或扭矩单项。

`Airfoil comparison` 表在 `Compare uniform airfoils` 模式完成后填充，包含：

- `rank`：按 fitness 从低到高排序的名次
- `airfoil_id`：该候选整支桨使用的翼型 ID
- `D`：该候选优化后选中的螺旋桨直径，单位 m
- `fitness`：该候选优化后的目标函数值，越低越好
- `target_error`：目标误差比例
- `T`：优化后推力，单位 N
- `Q`：优化后扭矩，单位 N*m
- `P`：优化后功率，单位 W
- `eta`：效率
- `CT`：推力系数
- `CQ`：扭矩系数
- `CP`：功率系数
- `evaluations`：该候选消耗的评估次数
- `warnings_count`：该候选结果中的 warning 数量

对比模式结束后，排名第一的候选会自动成为当前 best result，因此 `Apply best to Base Calculate` 和导出按钮默认使用该最佳候选的几何、历史和摘要。

## 14. 本地数据目录

项目包含本地数据目录：

```text
data/
  airfoils/
  blade_geometries/
  designs/
```

用途：

- `data/airfoils/`：存放翼型 DAT、导入 polar CSV、保存的 XFOIL polar
- `data/blade_geometries/`：存放桨叶几何 CSV
- `data/designs/`：存放 Optimization Design 和 Target Optimization 的几何、历史、摘要导出

Git 行为：

- 目录结构和 `.gitkeep` 会提交
- 用户数据文件默认被 `.gitignore` 忽略

这样既保留标准存储位置，又避免把本地实验数据误推到 GitHub。
