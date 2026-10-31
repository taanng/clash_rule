# AGENTS.md

本文件说明在本仓库中生成 OpenClash/Mihomo YAML 时必须遵循的流程。

## 目标

本项目将 `Custom_Clash_custom.ini` 中的规则和分组转换为完整的
Mihomo/Clash YAML。节点通过远程 `proxy-provider` 动态获取，不再使用
Subconverter 生成订阅。

默认输出：

```text
yaml/mihomo-config.yaml
```

该文件可放入私有 HTTP 静态目录，其访问地址即可作为 OpenClash 订阅链接。

## 目录约定

```text
Custom_Clash_custom.ini    规则和分组模板，是分流逻辑的主要来源
Custom_*.yaml              远程规则源，保持当前根目录路径
py/generate_mihomo_config.py
                           生成器
yaml/                      生成的 Mihomo YAML
provider.local.yaml        私有节点 provider 配置，不得提交
generated/                 GeoSite、GeoIP 等运行数据，不得提交
```

不要为了整理目录而移动根目录的 `Custom_*.yaml`。模板中的 jsDelivr URL
直接引用这些路径，移动后会导致订阅规则断链。若确需移动，必须同时修改
`Custom_Clash_custom.ini` 中全部相关 URL，并完成提交和推送。

## 敏感信息规则

节点 provider URL 通常包含 `key`、token 或密码，必须视为凭据。

- 不要在回复、日志、提交信息或 `AGENTS.md` 中输出完整 provider URL。
- 不要将 `provider.local.yaml`、`yaml/mihomo-config.yaml` 提交到公开仓库。
- 不要使用 `git add -f` 强制添加上述文件。
- 生成文件应保持权限 `600`。
- 订阅链接本身也包含访问控制信息，只可私下提供给信任的设备或用户。
- 在公开或共享订阅前，必须检查文件权限、仓库状态和托管位置。

当前 `.gitignore` 已忽略 `provider.local.yaml` 和 `generated/`，但未忽略
`yaml/`。每次提交前必须确认不包含生成的 YAML：

```bash
git status --short
```

若用户要求调整 `.gitignore`，不要反向撤销用户自己的修改。

## 私有 provider 配置

生成器默认读取项目根目录的 `provider.local.yaml`：

```yaml
provider:
  name: provider
  url: "http://<host>:<port>/<path>?key=<secret>"
  interval: 3600
```

要求：

- `url` 必须是 HTTP(S) 绝对地址。
- `interval` 单位为秒，不得小于 60。
- 文件权限必须为 `600`。
- 若该文件不存在，先向用户确认 provider 地址，或从用户指定的私密来源恢复。
- 不要用占位地址生成“成功”的订阅文件。

## 标准生成流程

在项目根目录执行：

```bash
cd /home/tang/clash_rule

test -f provider.local.yaml
chmod 600 provider.local.yaml

python3 -m py_compile py/generate_mihomo_config.py
python3 py/generate_mihomo_config.py

chmod 600 yaml/mihomo-config.yaml
```

生成器会自动：

- 读取 `Custom_Clash_custom.ini`。
- 转换 `GEOSITE`、`GEOIP`、`FINAL` 等内联规则。
- 为远程规则创建 `rule-providers`。
- 将节点 provider 写入 `proxy-providers`。
- 生成 `proxy-groups`，并让相关分组通过 `use` 引用节点 provider。
- 把 `♻️ 自动切换` 转为 `fallback` 分组。
- 校验分组引用、provider 引用和规则目标。
- 使用 `600` 权限写入 YAML。

不要在生成后手工编辑 `yaml/mihomo-config.yaml`。需要变化时应修改模板、
规则源或生成器，然后重新生成。

## Mihomo 校验

YAML 语法通过不代表 OpenClash 能加载。至少使用 Mihomo/Meta 内核执行：

```bash
/tmp/mihomo-1.19.33/mihomo \
  -d /home/tang/clash_rule/generated \
  -t -f /home/tang/clash_rule/yaml/mihomo-config.yaml
```

成功输出必须包含：

```text
configuration file ... test is successful
```

如果测试二进制不存在，从官方 `MetaCubeX/mihomo` release 获取 linux-amd64
版本。不要使用不支持 Hysteria2 的旧版 Clash Premium 作为最终验证工具。

仅在 `-t` 之后，才可进行运行时 provider 测试。测试时应：

- 使用临时配置目录。
- 改用未占用的代理端口和控制端口。
- 只监听 `127.0.0.1` 做测试。
- 查询 `/providers/proxies/<provider-name>`。
- 确认节点数大于 0，且类型包含当前节点使用的协议。
- 测试结束后停止临时进程。
- 不在日志或回复中输出节点密码、UUID 或 provider 完整 URL。

写入本文件时，已知 provider 包含 4 个节点：1 个 Hysteria2、3 个 VLESS，
其中 2 个节点名称匹配 `racknerd`。节点数可能随 provider 更新，不应硬编码。

## 分组和节点命名

`Custom_Clash_custom.ini` 中的 `♻️ 自动切换` 只匹配名称含 `racknerd`
的节点。若 provider 更新后不再包含该名称，自动切换组会为空。

遇到这种情况，应先检查脱敏后的节点名称，再让用户决定：

1. 调整模板中的过滤表达式。
2. 在 provider 侧统一节点命名。
3. 取消专用过滤，改用全部节点。

不要未经说明直接去掉过滤条件。

## 规则文件更新

生成结果中的规则提供者使用远程 URL。修改根目录 `Custom_*.yaml` 后，只有在
对应修改已提交并推送到模板引用的 GitHub 分支后，最终订阅才会更新。

只在本机修改规则文件但没有推送，不应声称订阅中的规则已经更新。

## 静态节点模式

默认模式必须保持 `proxy-provider`，以保留节点自动刷新和健康检查。

只有用户明确要求“把节点写死”时才可改为静态 `proxies`。此时必须说明：

- 节点不会随 provider 自动更新。
- 明文节点凭据会直接进入 YAML。
- 仍须执行 Mihomo 配置测试。

## 发布为订阅

生成的 YAML 只有放到 OpenClash 可访问的 HTTP(S) 地址后，才会形成订阅链接。

发布前确认：

- OpenClash 设备能访问托管主机。
- 不使用公开 GitHub Raw、公开对象存储或公开静态站点。
- 最好使用局域网私有地址、带认证的 HTTPS 或受控的 VPS。
- 启动网络监听服务前先告知用户暴露范围；涉及 root、sudo 或宿主机提权时，
  必须先取得用户明确确认。

## 完成标准

一次合格的 YAML 修改应同时满足：

- 使用私有 `provider.local.yaml` 完成生成。
- `python3 -m py_compile` 成功。
- 生成器内部引用校验成功。
- Mihomo `-t` 测试成功。
- provider 运行时能加载到节点。
- YAML 权限为 `600`。
- 未公开输出 provider URL、节点凭据或可访问的私密订阅链接。
