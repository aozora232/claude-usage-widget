# claude-usage-widget

Claudeサブスクリプション(Pro/Max)の使用量残量をWindowsデスクトップに
常時表示する、タスクトレイ常駐ウィジェットです。

- 5時間 / 週間 / 追加クレジット(月間制限=100%)の使用率バー表示
- 折りたたみ時はバー3本+リセットパイと⟳(手動更新)▼(展開)のみのスリム表示
- リセットパイ(グレーの円): 5時間ウィンドウのリセットまでの残り時間。
  満タン=リセット直後、空=まもなくリセット(1分ごとに自動更新、API呼び出しなし)
- ▼クリックで詳細パネル(モデル別制限とリセット時刻、追加クレジット残額、更新間隔設定)
- APIプリペイド残高の手動記録欄(詳細パネル内)

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
- 短時間に連続で更新するとAPIがレート制限(HTTP 429)を返すことがあります。
  その間は⟳がアンバー色になります(バーは直前の取得値のまま)。次の自動更新が
  成功すると元に戻るので、待てば回復します。

## ライセンス

MIT
