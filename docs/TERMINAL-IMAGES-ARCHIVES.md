# Terminal images and archive shortcuts / 终端图片与解压快捷操作

## Images / 图片

The terminal toolbar's **Terminal images / 终端图片** switch is off by default. Its value is saved in shared workspace preferences and applies to open and future terminal tabs, including standalone windows. Enable it when inline images are useful. Previously ignored sequences are not replayed when enabling it.

工具栏中的“终端图片”默认关闭。开关保存在工作空间偏好中，对已打开和之后创建的终端生效，也适用于独立窗口。打开开关后，之前忽略的图片不会重新显示。

Pinned `@xterm/addon-image` **0.9.0** supports SIXEL and iTerm IIP inline PNG, JPEG and GIF. GIF is static. Kitty graphics, arbitrary HTML and SVG are not supported. Images must arrive as terminal protocol payloads; the app does not fetch image URLs or load paths from filenames/metadata. IIP file-download sequences (`inline=0`) are ignored by this version of the addon. See the [upstream addon documentation](https://github.com/xtermjs/xterm.js/tree/f447274f430fd22513f6adbf9862d19524471c04/addons/addon-image).

当前固定使用 0.9.0，支持 SIXEL 和 iTerm IIP 内嵌 PNG、JPEG、GIF，GIF 只显示静态画面。不支持 Kitty、HTML 或 SVG。图片必须直接包含在终端协议数据中，不会根据文件名或元数据访问本地文件、远程路径或网址；文件下载序列会被忽略。

Bounds per terminal:

- Fewer than 2,097,152 pixels per IIP image before and after scaling; SIXEL decoder capped at 2,097,152 pixels.
- 16 MB FIFO image cache (addon uses decimal MB). Old images become placeholders. With 12 terminals the image caches total at most 192 MB; decoder, terminal queue and browser rendering memory are additional.
- 8 MiB SIXEL sequence; 8 MiB decoded IIP payload (base64 transport up to about 11.2 MiB).
- No automatic terminal size reports from the addon.

每个终端限制：单张图片约 200 万像素，缓存 16 MB；SIXEL 序列 8 MiB，IIP 解码后数据 8 MiB。IIP 的 base64 传输内容最多约 11.2 MiB。缓存满后按先入先出顺序淘汰旧图，并显示占位图。12 个终端的图片缓存合计最多 192 MB，解码和浏览器绘制仍会额外占用内存。

`SafeImageAddon` is a compatibility adapter for the pinned addon's internal streaming handlers. Decode exceptions and rejected bitmap promises are consumed; a 2-second timeout resumes terminal parsing. Each decode receives a separate storage capability; timeout and disposal invalidate it and close late bitmaps, preventing stale images from moving a newer cursor or writing into disposed storage. Reassess this adapter before upgrading the dependency. The addon's no-`createImageBitmap` fallback is retained for WebKit. The manager waits for queued parsing before toggling storage and disposes resources on terminal teardown. Existing output ACKs remain in the `term.write` completion callback.

图片解码失败时会继续解析后续输出。超过 2 秒仍未完成的解码会失效；之后才返回的图片不会插入新的光标位置，终端关闭后也不会写入缓存。WebKit 没有 `createImageBitmap` 时使用插件自带的回退方式。插件升级时必须重新检查兼容代码。

## Archive command fill / 填入解压命令

Ctrl/Command + left click a **standalone printed path** ending in `.tar`, `.tar.gz`, `.tgz`, `.tar.bz2`, `.tbz2`, `.tar.xz` or `.zip`. Wrapped paths, spaces, Unicode, apostrophes and shell punctuation are preserved. This shares the directory path link provider, so absolute archive paths are handled once. Quotes inside a path are literal filename characters; the app does not parse shell quoting, prompts, `ls -l`, URLs or arbitrary command output into paths. Leading/trailing whitespace is trimmed as with existing directory links; filenames requiring that whitespace are unsupported.

按住 Ctrl/Command，左键单击独占一行的压缩包路径，可填入解压命令。支持上面列出的扩展名，以及换行显示的长路径、空格、中文和路径中的引号。引号视为文件名本身的一部分，不会当作 shell 语法去除。不能识别提示符、`ls -l` 明细或任意文本中的路径；首尾空白会被去掉，因此不适合首尾带空白的文件名。

This is for the app's remote Linux/POSIX-shell terminals. Relative paths require a known absolute shell working directory. Controls, Windows-style backslashes, URLs and `..` traversal segments are rejected. Paths are converted to absolute paths and single-quoted, including embedded apostrophes. Commands are:

```sh
tar -xf '/absolute/archive.tar.gz' -C '/absolute' --keep-old-files
unzip -n '/absolute/archive.zip' -d '/absolute'
```

The command is only pasted at an enhanced shell's confirmed empty prompt while connected. Busy shells, unknown command-line state and existing text cause a refusal; existing input is retained. No newline is sent. The hint asks the user to review and press Enter. The destination is the archive's parent directory and existing files are retained (`tar --keep-old-files` can report an error on collisions).

此功能适用于远端 Linux/POSIX shell。相对路径必须有已知的绝对工作目录；拒绝控制字符、Windows 反斜杠路径、网址和包含 `..` 的路径。命令只能填入已经确认就绪的空命令行。正在执行任务、命令行状态不明或已有输入时都会拒绝，并保留已有内容。填入时不发送换行；界面提示检查后按 Enter 执行。解压目标是压缩包所在目录，并保留已有文件。

## Verification / 验证

- `npm test --prefix frontend`: helper bounds/lifecycle/decode expiry plus component tests using real headless xterm cells for wrapped Unicode archive paths, empty prompt, busy prompt, unknown cwd and preservation of input.
- `npm run build --prefix frontend`: TypeScript and production build.
- `node scripts/check-terminal-images.cjs`: local Vite + Playwright with installed Edge Chromium and WebKit. Actual 8×8 PNG IIP and 8×6 SIXEL both decode red RGBA pixels and create a rendered canvas. WebKit is tested with `createImageBitmap` removed. Corrupt PNG and ignored download sequences leave parsing live. Chromium's artificially delayed decoder is released after timeout and after disposal; neither inserts an image. Screenshots/results are written under ignored `work/feature8/` / standard output. No SSH or production server is used. This does not establish native macOS Tauri behavior.
