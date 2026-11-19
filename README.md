# ctree_heights_plot

一般化コラッツ写像 $(p, Q)$ の軌道計算・逆向きコラッツ木（CTree）の可視化・大規模探索を行うための解析ツール群および対話型 Web アプリケーションです。

* **Qiita Advent Calendar 2026 連載**: [CTree観察記〜コラッツ予想のつくる森](https://qiita.com/advent-calendar/2026/ctree_watching)
* **GitHub Repository**: `https://github.com/ctreephile/ctree_heights_plot`
---

## 概要：一般化コラッツ写像 $(p, Q)$

自然数 $n$ に対して、$d = p - 1$ と定数組 $Q = [q_1, q_2, \dots, q_{d-1}]$（標準条件 $q_r \equiv d - r \pmod d$）を用い、次の写像 $T_{p, Q}(n)$ を反復します。

$$
T_{p, Q}(n) =
\begin{cases}
n / d & (n \equiv 0 \pmod d) \\
p n + q_r & (n \equiv r \pmod d,\; r \neq 0)
\end{cases}
$$

$p = 3,\; Q = [1]$ のときが通常のコラッツ予想（$3n + 1$ 問題）に一致します。

---

## Web アプリケーションの起動方法

ビルド済みのフロントエンド（`frontend/dist/`）が同梱されているため、Python 環境を準備するだけでそのまま起動できます。

### 1. 依存パッケージのインストール

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows の場合: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. サーバーの起動

```bash
python run_app.py
```

ブラウザで `http://127.0.0.1:8000` を開くと Web アプリを利用できます（`--host` や `--port` で変更可能です）。

### 主な機能
* **Heights Plot & ループ一覧**: 任意の $(p, Q)$ について $n = 1 \dots N$ の軌道を計算し、到達ループごとの吸引率・ジニ係数・高さプロットを表示します。
* **CTree 可視化・幅スペクトル**: 各ループを根（$h = 0$）として逆向きに木を伸ばし、$q_r$ 別の枝色分けや世代ごとのノード数スペクトルを確認できます。
* **Snow Crystal 結晶成長モード & GIF 生成**: 放射状に広がる結晶成長の可視化および GIF アニメーション書き出しに対応しています。
* **2ツリー重ね合わせ比較**: 2 つの $(p, Q)$ の木を重ねて構造の一致やクローン関係を比較できます。
* **$p = 4$ ヒートマップ探索**: $(q_1, q_2)$ 平面のループ数・ノード数・ファミリー軌道を俯瞰できます。

---

## データベース・サマリーデータの生成（任意）

Web アプリの基本的な計算・可視化はデータベースなしでもリアルタイムで動作します。大規模探索データベース（`data/p{p}/summary_p{p}.db`）や $p = 4$ ヒートマップ用サマリーを利用したい場合は、同梱のバッチスクリプトを実行して生成できます。

```bash
# 例: p=4 ヒートマップ用サマリー (80x80) を outputs/p4_grid_80x80/ へ生成
python batch_p4_summary.py --grid-size 80

# 例: p=3, 5..9 の探索データベースを data/p{p}/summary_p{p}.db へ生成
python batch_p5.py
```

※ `batch_p3.py`, `batch_p5.py`, `batch_p6.py`〜`batch_p9.py` などの実行にはシステムによって数分〜数十分かかる場合があります。

---

## テストの実行

```bash
pytest
```

## ライセンス

[MIT License](LICENSE)

