# SNS Autopilot（クレカ・マイル・旅行アカウント用）

X と Instagram の運用を GitHub Actions で毎日自動で回す仕組みです。

```
 毎日 20:17          あなた（スマホでOK）       毎日 6時〜24時（30分ごと）     毎日 23:43 / 毎週月曜
┌────────────┐     ┌──────────────┐      ┌────────────────┐        ┌───────────────┐
│① リサーチ   │     │ Pull Requestを │      │③ 予約時刻になった │        │④ 数値を収集     │
│  (Web検索)   │ ──▶ │ 見て、OKならマージ│ ──▶ │  投稿を公開      │ ──▶    │  週1で分析レポート │
│② 台本・画像・ │     │ (直したければ編集)│      │  X / Instagram   │        │  「学び」を更新    │
│  動画を作成   │     └──────────────┘      └────────────────┘        └───────┬───────┘
└─────▲──────┘                                                                   │
      └──────────────────── 次の台本に「学び」を反映 ◀──────────────────────────────┘
```

| 何を | どうやって |
|---|---|
| リサーチ | Claude が Web 検索で直近のカード・マイル・航空券キャンペーンを調べ、出典つきで `research/` に保存 |
| 台本作成 | X 4投稿/日、Instagram カルーセル（月水金）・リール（火木土）の台本を作成 |
| 画像・動画 | カルーセル画像（1080×1350）とリール動画（1080×1920, 15〜30秒）を自動生成 |
| 安全チェック | 裏の取れない数字・NGワード・文字数オーバーを PR 上で ⚠️ 警告。アフィリエイト投稿には【PR】を自動付与（ステマ規制対策） |
| 投稿 | X API / Instagram Graph API で予約時刻に投稿 |
| 分析 | 毎日インプレッション・保存・シェア等を収集。毎週月曜に Claude が分析して `reports/` と `data/learnings.md` を更新 |

---

## セットアップ（初回だけ・1〜2時間）

### 1. このリポジトリを GitHub に置く
- Instagram の画像は「公開URL」が必要です。いちばん簡単なのは **Public リポジトリ** にすること（`media_host: github_raw`）。
- Private にしたい場合は Cloudflare R2 を用意して `config/account.yaml` の `media_host: r2` に変更（後述）。
- リポジトリの **Settings → Actions → General** で
  - Workflow permissions: **Read and write permissions**
  - **Allow GitHub Actions to create and approve pull requests** にチェック

### 2. Claude API キー
1. https://console.anthropic.com/ で API キーを発行
2. GitHub リポジトリの **Settings → Secrets and variables → Actions → New repository secret** に `ANTHROPIC_API_KEY` として登録

### 3. X API キー
1. https://developer.x.com/ で開発者登録 → Project と App を作成
2. App の **User authentication settings** で権限を **Read and write** に設定
3. **Keys and tokens** から次の4つを発行し（権限変更の**後**に Access Token を再発行すること）、Secrets に登録

| Secret名 | 中身 |
|---|---|
| `X_API_KEY` | API Key（Consumer Key） |
| `X_API_SECRET` | API Key Secret |
| `X_ACCESS_TOKEN` | Access Token |
| `X_ACCESS_TOKEN_SECRET` | Access Token Secret |

> X API は有料プラン／従量課金です。料金体系は変わりやすいので、開発者ポータルで最新の料金を確認してください。投稿（1日4件）と数値取得（1日1回）が使える範囲で一番安いものを選べば十分です。

### 4. Instagram API
前提: Instagram が **プロアカウント**（ビジネス or クリエイター）で、**Facebook ページ** と連携済み。

1. https://developers.facebook.com/ でアプリを作成（ユースケース: Instagram / ビジネス）
2. 権限: `instagram_basic`, `instagram_content_publish`, `instagram_manage_insights`, `pages_show_list`, `pages_read_engagement`
3. **アクセストークンは「システムユーザートークン」を推奨**（Meta ビジネススイート → ビジネス設定 → システムユーザー で発行。期限なしにできる）。通常のユーザートークンは60日で切れます。
4. Graph API エクスプローラで `GET /me/accounts?fields=instagram_business_account` を実行し、出てきた `instagram_business_account.id` を控える

| Secret名 | 中身 |
|---|---|
| `IG_USER_ID` | 上で控えた Instagram ビジネスアカウントID |
| `IG_ACCESS_TOKEN` | アクセストークン |

### 5. 設定ファイルを自分用に書き換える
- `config/account.yaml` … アカウント名・キャラ・ターゲット・投稿時刻・デザインカラー・`handle`
- `config/facts.yaml` … **最重要**。公式サイトで確認したカード情報（年会費・還元率・特典）を書く。AIはここと当日のリサーチにある数字しか使いません。アフィリエイトの紹介リンクもここに入れます。
- `assets/bgm/` … リールに流すBGM（mp3）を入れるとランダムに使われます（**商用利用OKの音源のみ**）。空なら無音。

### 6. 動作確認
GitHub の **Actions** タブ →「1. 台本と下書きを作る」→ **Run workflow**。
数分後に Pull Request が届けば成功です。中身を確認してマージすると、予約時刻に投稿されます。

---

## 毎日の運用（承認制のあいだ）

1. 毎晩 20時ごろ、翌日分の Pull Request が届く（GitHub アプリの通知をオンにしておくと便利）
2. ⚠️ 要確認 の項目だけでも目を通す（数字が公式と合っているか）
3. 直したい投稿は `queue/日付/x-01/post.json` などを GitHub 上で編集、不要な投稿はフォルダごと削除
4. **マージ**（翌日の最初の投稿時刻〜6時間後までにマージすれば間に合います）

品質が安定したら `config/account.yaml` の `approval: auto` にすると、確認なしで投稿されるようになります。

## 収益化に向けて
- アフィリエイト（A8.net、もしもアフィリエイト、ASPのクレカ案件など）に登録したら、`config/facts.yaml` の該当カードに `affiliate_url` を入れるだけ。紹介する投稿に【PR】/#PR が自動で付き、Xでは紹介リンクがツリー（返信）に入ります（本文にURLがあると表示が伸びにくいため）。
- Instagram はキャプションのリンクが押せないので、プロフィールのリンク（lit.link 等）に案件をまとめておくのが定番です。
- 週次レポートに「収益化に向けた進捗と次の一手」が出るので、それを見て判断してください。

## 注意
- **ステマ規制（景品表示法）**: 紹介報酬のある投稿には広告であることの表示が必要です。PR表記を消さないでください。
- **クレカの情報**: 年会費・還元率・キャンペーンはよく変わります。`facts.yaml` は月1回は見直してください。
- **プラットフォームの規約**: 同じ内容の連投や、大量の自動いいね・フォローは凍結の原因になります。この仕組みは投稿と数値取得だけを行います。
- 失敗した投稿は `data/errors.jsonl` に記録されます。

## 費用の目安
| 項目 | 目安 |
|---|---|
| GitHub Actions | Public リポジトリなら無料。Private でも無料枠（月2,000分）にほぼ収まる設計 |
| Claude API | 1日1回のリサーチ+台本作成+週1分析で、月 数千円程度（投稿量・effort設定で変動） |
| X API | プランにより変動（開発者ポータルで確認） |
| Instagram API | 無料 |

## Private リポジトリで使う場合（Cloudflare R2）
`config/account.yaml` で `media_host: r2` にし、Secrets に `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_BASE_URL`（公開バケットのURL）を登録してください。

## ローカルで試す（開発者向け）
```bash
pip install -r requirements.txt   # 日本語フォント(fonts-noto-cjk)とffmpegも必要
PYTHONPATH=src python -m autopilot preview tests/sample_plan.json   # APIキー無しで画像・動画だけ生成
PYTHONPATH=src ANTHROPIC_API_KEY=... python -m autopilot generate     # 本番と同じ下書き生成
PYTHONPATH=src python -m autopilot publish --dry-run                  # 投稿対象の確認だけ
```
