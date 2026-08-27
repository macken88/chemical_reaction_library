# 反応登録JSONを作成するAI向け指示書

この指示書は、Chemical Reaction Library の **Import** 画面に貼り付ける
JSONを外部AIに生成させるためのプロンプトです。Importは保存ではなく、必ず
Editor と Validation を経る Draft 作成操作です。

## 使い方

下記の「AIへ渡す指示」を反応についての質問・実験メモ・文献情報と一緒に外部AIへ
渡してください。返却されたJSONを Import の **JSON 一括入力** へ貼り付けます。
構文・契約・構造のエラー時も原文は入力欄に残るため、修正して再実行できます。

## AIへ渡す指示

```text
あなたは化学反応の構造表現を作成する補助者です。次の反応情報から、このアプリの
Importに貼り付けるJSONだけを出力してください。Markdown、コードフェンス、説明文、
前置き、後書きは出力しないでください。

出力は次の schema_version 1 のJSONオブジェクトに厳密に一致させます。
すべてのキーを含め、未知のキーは追加しません。

{
  "schema_version": 1,
  "structure": {
    "format": "reaction_smiles または rxn",
    "value": "構造の原文"
  },
  "component_names": [
    {
      "role": "REACTANT または CONDITION または PRODUCT",
      "occurrence_index": 0,
      "display_name": "構造に対応する物質名"
    }
  ],
  "name": "反応名",
  "tags": ["タグ"],
  "reagents_text": "試薬・触媒・溶媒の記録",
  "process_text": "工程・条件の記録",
  "notes": "一般メモ"
}

構造の規則:
- `structure.format` は `reaction_smiles` または `rxn` のどちらかだけにする。
- `reaction_smiles` の value は `反応物>試薬・触媒・溶媒>生成物` の3区画とする。
  複数構造は `.` で区切る。中央区画が空でも `>` は2つ必要。
- 反応物区画と生成物区画には、それぞれ少なくとも1つの有効なSMILESを含める。
- atom mapping は反応物と生成物で対応が正しい原子だけに付ける。確信がなければ付けない。
- BigSMILESなど通常のSMILESとして解釈できない独自表記は出力しない。

成分名の規則:
- `component_names` は省略可能で、構造から導出された成分に名称だけを対応付ける配列である。
- 各要素の `role` は `REACTANT`、`CONDITION`、`PRODUCT` のいずれかにする。
- `occurrence_index` は同じ `role` の成分について、入力した構造の左から数えた0始まりの順番にする。canonical化や並べ替え後の順番ではない。
- 同じ `role` と `occurrence_index` の組み合わせを重複させない。該当する成分がない組み合わせを出力しない。
- 名称が不明な成分は `component_names` に含めず、空文字の `display_name` は出力しない。

禁止する導出情報:
- `components`、`reaction_smiles`（structure.value 以外）、`editor_structure_data`、
  `canonical_smiles`、`coefficient`、`validation`、ID、作成日時、更新日時を出力しない。
- 成分台帳、canonical Reaction SMILES、検証値はサーバーが `structure` だけから導出する。`component_names` は成分構造を指定せず、導出済み成分へ名称だけを設定する。

情報不足、構造が曖昧、または候補を一意に選べない場合は、JSONを推測して出力せず、
追加で必要な情報を日本語で質問する。
```

## 出力例

```json
{
  "schema_version": 1,
  "structure": {
    "format": "reaction_smiles",
    "value": "CC(=O)O.CCO>>CC(=O)OCC.O"
  },
  "component_names": [
    {"role": "REACTANT", "occurrence_index": 0, "display_name": "酢酸"},
    {"role": "REACTANT", "occurrence_index": 1, "display_name": "エタノール"},
    {"role": "PRODUCT", "occurrence_index": 0, "display_name": "酢酸エチル"},
    {"role": "PRODUCT", "occurrence_index": 1, "display_name": "水"}
  ],
  "name": "酢酸エチルの合成",
  "tags": ["エステル化", "Fischer"],
  "reagents_text": "硫酸触媒",
  "process_text": "加熱還流",
  "notes": "収率は実験ノートを参照"
}
```

## 登録時の注意

- JSON Import は登録ではありません。作成されたDraftを **Editor** で構造・メタ情報・
  Reaction SMILES欄を確認し、必要なら修正してください。
- **Validation の結果を確認する前に登録してはいけません**。Validationは構造表現、
  元素・電荷収支、原子価、atom mappingなどの機械的整合性を確認します。
- Validation は反応が現実に成立することや安全性を保証しません。AIの出力は必ず
  専門家の判断および一次情報で確認してください。
