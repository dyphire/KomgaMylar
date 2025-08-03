# komga-mylar

一个用于 Komga 漫画服务器与 Mylar 格式之间元数据导入导出的命令行工具

---

## 功能

- 从指定 Komga 库导出所有系列（series）元数据为 Mylar 格式的 `series.json` 文件
- 支持导出时保持 Komga 库根目录的原始目录结构
- 可选下载系列封面图片
- 读取 Komga 漫画目录中的 `series.json` 文件，批量更新 Komga 中系列及其图书的元数据
- 支持通过命令行参数或环境变量配置 Komga 地址、用户名、密码、库ID等

---

## 安装

推荐使用 Python 3.7 及以上版本

安装依赖：

```bash
pip install requests python-dotenv
```

`python-dotenv` 可选，用于从 `.env` 文件加载环境变量

---

## 使用

```bash
python komga-mylar.py [OPTIONS]
```

### 参数说明

| 参数                             | 说明                                                             | 示例                          |
| -------------------------------- | ---------------------------------------------------------------- | ----------------------------- |
| `--url`                        | Komga 服务器地址（含协议和端口）                                 | `http://localhost:25600`    |
| `--username`                   | Komga 登录用户名                                                 | `admin`                     |
| `--library-id`                 | 需要操作的库 ID                                                  | `123`                       |
| `--output`                     | 导出目录，默认为当前目录                                         | `./export`                  |
| `--library-root`               | Komga 库根目录，用于保持导出目录的相对结构                       | `/mnt/comics/komga_library` |
| `--save-cover`                 | 是否下载并保存系列封面，默认不下载                               | (无参数，设置此开关即可)      |
| `--update-from-mylar-metadata` | 从 Komga 漫画目录中的 `series.json` 读取元数据，批量更新 Komga | (无参数，设置此开关即可)      |

### 示例

导出库ID为 123 的系列元数据到漫画原始目录：

```bash
python komga-mylar.py --url http://localhost:25600 --username admin --library-id 123
```

导出库ID为 123 的系列元数据到 `./export`，并下载封面：

```bash
python komga-mylar.py --url http://localhost:25600 --username admin --library-id 123 --output ./export --save-cover
```

从 Komga 漫画目录中的 `series.json` 更新 Komga 元数据：

> [!NOTE]
>
> 使用此功能的前提是脚本和 Komga 服务必须处于同一台设备上

```bash
python komga-mylar.py --url http://localhost:25600 --username admin --library-id 123 --update-from-mylar-metadata
```

---

## 环境变量支持

可以在 `.env` 文件或系统环境变量中设置：

- `KOMGA_URL`
- `KOMGA_USERNAME`
- `KOMGA_PASSWORD`
- `KOMGA_LIBRARY_ID`

这样就无需每次运行时输入

---

## 注意事项

- 确保 Komga 服务器可用且账户权限允许访问目标库和修改元数据
- `library-id` 可在 Komga WebUI 界面查看
- 导出时建议设置 `--library-root` 以保持文件夹结构
- 更新元数据时请确保漫画目录中的 `series.json` 格式正确

---

## 相关项目

- [KomgaBangumi](https://github.com/dyphire/KomgaBangumi)

## 许可证

MIT License

---

## 贡献

欢迎提交 issue 和 pull request！
