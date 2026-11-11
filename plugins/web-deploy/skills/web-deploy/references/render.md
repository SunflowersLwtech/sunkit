<!-- public rewrite; the original internal copy is not shipped -->

# Render 部署（GHCR 镜像模式）

**先看这里：发布优先走各仓库自己的 CI，本地 Docker 只是兜底。**

| 服务 | 怎么发 | 验证 |
|---|---|---|
| 任意服务 | push 到 `main`（动到对应目录）触发 `backend-image.yml` 这类构建 workflow，或 `gh workflow run <image>.yml` | workflow 自己等 Render live 并校验健康端点（如 `/healthz/`）报出该 commit |

CI 用 `GITHUB_TOKEN` 推 GHCR、用 `RENDER_API_KEY` secret 触发部署。
镜像里烧了 `RELEASE_SHA`，所以"部署成功"和"线上真的是这个提交"是两件分开验证的事。

## 模式与凭据

- 模式：本地/CI 构建 `linux/amd64` 镜像 → GHCR（private）→ Render 通过 registry
  credential 拉取。不用 Render 的 GitHub 连接 —— 适合"GitHub 身份被旧 Render 账号
  占用"这类连不上的情况。
- 凭据（全部走环境变量，不进 argv、不进仓库）：
  - `RENDER_API_KEY`：Render API key（Dashboard → Team Settings → API Keys）；
  - `RENDER_OWNER_ID`：Render 的 owner/team id（`tea-…`）；
  - `RENDER_REGISTRY_CRED`：Render 里的 registry credential id（`rgc-…`），
    指 GHCR 的拉取凭据 —— 必须是镜像所属账号名下的 PAT（`read:packages`）；
  - 本地推送用 `gh auth token`（注意 `docker login` 会切换本机登录态）。
- `scripts/render.sh` 读本目录的 `services.json`（仓里是一份占位示例，替换成你自己的服务）。

## 本地 Docker 挂了怎么办

Docker Desktop 起不来时，`build` 支持远程原生构建（不是 QEMU 模拟）：

```bash
REMOTE_BUILD_HOST=user@your-build-host \
REMOTE_BUILD_KEY=/path/to/ssh-key \
GHCR_USER=your-gh-account \
  bash scripts/render.sh release my-api
```

它会：校验远端是 x86_64 → rsync 构建上下文（排除 .venv/.env/db.sqlite3）→
用 `gh auth token` 登录 GHCR → 原生构建并推送 → **无论成败都清理**上下文目录、
镜像与 GHCR 登录态。

用你自己的构建机（备用 VM、云主机都行）：不要拿生产服务器当构建机。

## 旁边常见的一个坑：Supabase Storage 作媒体桶时

⚠️ **Supabase 的 S3 端点不支持预签名 URL**（query-string SigV4 一律 403，裸 boto3
也一样，只有 header 签名能用）。所以 `MEDIA_STORAGE_PUBLIC_BASE_URL` 必须保持设置
（它让 `AWS_QUERYSTRING_AUTH=False`），桶必须保持 public，否则
`default_storage.url()` 返回的每个链接都 403。从 Railway/Tigris 这类支持预签名的
存储迁过来时，当初 setup 里没配的这条会在迁移后咬人。
