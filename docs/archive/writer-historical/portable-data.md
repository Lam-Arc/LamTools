# Writer Portable Data

Writer 的默认数据目录是 `members/writer/data/`。

启动优先级：

1. 显式 `LAMWRITER_DATA_DIR`
2. 项目内 `members/writer/data/`
3. 旧 AppData 数据库仅在新库不存在时复制一次

Packaged Electron 应用使用程序目录旁的 `data/` 和 `user-data/`。
