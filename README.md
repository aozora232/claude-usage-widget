# claude-usage-widget

Claudeサブスクリプション(Pro/Max)の使用量残量をWindowsデスクトップに
常時表示する、タスクトレイ常駐ウィジェットです。

- 5時間セッション使用率 / 週間使用率(バー表示、リセット時刻つき)
- 追加使用クレジット(extra usage)の残額を自動取得
- APIプリペイド残高の手動記録欄
- ▼クリックで詳細パネル(モデル別制限の一覧、更新間隔設定)

## 必要条件

- Windows 10/11
- Python 3.10+
- [Claude Code](https://claude.com/claude-code) にログイン済みであること
  (`~/.claude/.credentials.json` の認証情報を読み取ります)

## セットアップ

```
pip install -r requirements.txt
python claude_usage_widget.py
```

コンソールなしで起動する場合は `pythonw claude_usage_widget.py`。

## Windows起動時に自動実行する

1. `Win + R` → `shell:startup` → Enter
2. 開いたフォルダに、以下を対象とするショートカットを作成:
   `pythonw.exe <このリポジトリのパス>\claude_usage_widget.py`

## 設定の保存先

`%APPDATA%\claude-usage-widget\config.json`
(ウィンドウ位置・更新間隔・最前面固定・プリペイド残高)

## 注意事項

- 本ツールは Claude Code の `/usage` コマンドが使う**非公開API**
  (`api.anthropic.com/api/oauth/usage`)を利用しています。仕様変更で
  予告なく動かなくなる可能性があります。
- アクセストークンの読み取りのみ行い、リフレッシュや書き換えは行いません。
  トークンが期限切れの場合はClaude Codeを一度起動してください。
- APIプリペイド残高(console.anthropic.com)には公開APIが存在しないため、
  手動入力です。

## ライセンス

MIT
