# Agent Hub

外部サービスの情報を参照しながらエージェントと会話するサービスの空のひな形です。
プロジェクト名は仮に `agent-hub` としています。

## 開発を始める

```sh
uv sync --locked
uv run agent-hub
```

Python 3.12、uv、Ruff を使用します。起動コマンドは準備完了メッセージを表示して終了します。
Webサーバーや画面はまだありません。

## 開発チェック

```sh
uv run ruff check .
uv run ruff format --check .
```

整形を適用する場合は `uv run ruff format .` を実行します。

## 構成

```text
src/agent_hub/
├── __main__.py          # 動作確認用エントリーポイント
├── conversations/      # 会話・メッセージ・セッション
├── agents/             # エージェントの実行とツール呼び出し
└── integrations/       # サービスごとの接続処理
    ├── gpt_live/
    ├── slack/
    ├── google_drive/
    ├── google_chat/
    ├── jira/
    ├── teams/
    ├── confluence/
    └── internet_search/
```

各パッケージは配置場所だけを用意した状態です。
認証、API呼び出し、会話保存、エージェント実行は未実装です。
GPT-Liveの具体的なサービス・APIは実装時に確定します。

Teams、Confluence、Internet Searchも接続用パッケージの配置のみです。
実際のサービス接続やインターネット検索はまだ実行できません。
Internet Searchの提供元・APIは実装時に確定し、検索結果のタイトル・URL・要約を
エージェントが参照できるようにする予定です。

現時点では環境変数の読み込み処理はありません。`.env` はGit管理対象外です。

## 次に実装すること

1. 会話UIとバックエンドAPIの方式を決める。
2. GPT-Liveの接続仕様を確定し、最初のエージェント会話を実装する。
3. ユーザー認証と接続情報の保管方法を実装する。
4. Slack、Google Drive、Google Chat、Jira、Teams、Confluenceを接続する。
5. Internet Searchの検索APIを選定し、検索結果の出典URLを会話で提示する。
6. 外部への送信・更新は、ユーザーの確認を経て実行する設計にする。
