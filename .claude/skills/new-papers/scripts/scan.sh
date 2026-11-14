#!/usr/bin/env bash
# Read PDFs without parsing them; keep local reports outside the runtime library.
set -euo pipefail

skill_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
repo_dir=$(cd -- "$skill_dir/../../.." && pwd)
source "$skill_dir/scripts/paths.sh"
brainstorming_root=$(select_brainstorming_root)
watch_dir="$skill_dir/state"
library_dir="$repo_dir/data/libraries/papers"
source_dirs=(
  "$brainstorming_root/Error Correction"
  "$brainstorming_root/Architecture/3.Trapped-Ion"
  "$brainstorming_root/Architecture/4.Neutral-Atom"
)

for dependency in jq sha256sum find sort stat; do
  command -v "$dependency" >/dev/null || { echo "Missing dependency: $dependency" >&2; exit 1; }
done
for directory in "${source_dirs[@]}" "$library_dir"; do
  [[ -d "$directory" && -r "$directory" && -x "$directory" ]] || {
    echo "Cannot access directory: $directory" >&2
    exit 1
  }
done

mkdir -p -- "$watch_dir"
scratch_dir=$(mktemp -d "$watch_dir/.scan.XXXXXX")
trap 'rm -rf -- "$scratch_dir"' EXIT
find "${source_dirs[@]}" -type f -iname '*.pdf' -print0 | sort -z > "$scratch_dir/source-paths"
find "$library_dir" -type f -iname '*.pdf' -print0 | sort -z > "$scratch_dir/library-paths"
find "$library_dir" -type f -name 'meta.json' -print0 | sort -z > "$scratch_dir/meta-paths"

hash_files() {
  local list_file=$1 output_file=$2 file before after digest modified
  : > "$output_file"
  while IFS= read -r -d '' file; do
    before=$(stat -c '%s:%y' -- "$file")
    digest=$(sha256sum < "$file")
    digest=${digest%% *}
    modified=$(TZ=Asia/Hong_Kong stat -c '%y' -- "$file")
    after=$(stat -c '%s:%y' -- "$file")
    [[ "$before" == "$after" ]] || { echo "File changed during scan: $file" >&2; return 1; }
    jq -cn --arg path "$file" --arg sha256 "$digest" --arg modified "$modified" \
      '{path: $path, sha256: $sha256, modified: $modified}' >> "$output_file"
  done < "$list_file"
}

hash_files "$scratch_dir/source-paths" "$scratch_dir/sources.jsonl"
hash_files "$scratch_dir/library-paths" "$scratch_dir/library.jsonl"
: > "$scratch_dir/metadata.jsonl"
while IFS= read -r -d '' metadata; do
  jq -c --arg path "$metadata" \
    '{path: $path, id: .id, title: (.title // ""), source_file: (.source_file // "")}' \
    "$metadata" >> "$scratch_dir/metadata.jsonl"
done < "$scratch_dir/meta-paths"

previous_report="$watch_dir/report.json"
ignored_file="$skill_dir/ignored.json"
[[ -s "$previous_report" ]] || previous_report="$scratch_dir/initial-report.json"
[[ -f "$ignored_file" ]] || ignored_file="$scratch_dir/empty.json"
echo '[]' > "$scratch_dir/empty.json"
echo '{"files": []}' > "$scratch_dir/initial-report.json"

jq -n --slurpfile sources "$scratch_dir/sources.jsonl" \
  --slurpfile library "$scratch_dir/library.jsonl" \
  --slurpfile metadata "$scratch_dir/metadata.jsonl" \
  --slurpfile previous "$previous_report" --slurpfile ignored "$ignored_file" \
  --arg brainstorming_root "$brainstorming_root" \
  --arg scanned_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" '
  def stem: split("/")[-1] | sub("\\.[^.]+$"; "") | sub("-[a-f0-9]{16}$"; "");
  def normal: ascii_downcase | gsub("[^a-z0-9一-龥]"; "");
  ($previous[0].files? // []) as $old_files |
  ($ignored[0] // []) as $ignored_hashes |
  if ($ignored_hashes | type) != "array" then error("ignored.json must be an array") else . end |
  ($sources | sort_by(.sha256) | group_by(.sha256) | map(
    . as $copies | .[0] as $file |
    [$library[] | select(.sha256 == $file.sha256) | {reason: "sha256", path}] as $exact |
    [$metadata[] | . as $record |
      [$copies[] | .path | stem | normal] as $names |
      [$copies[] | .path | stem | split(" - ") | .[-1] | normal] as $titles |
      ($record.source_file | stem | normal) as $source_name |
      ($record.title | normal) as $title |
      if $source_name != "" and ($names | index($source_name)) != null then
        {reason: "source_file", path: $record.path, title: $record.title}
      elif $title != "" and ($titles | index($title)) != null then
        {reason: "title", path: $record.path, title: $record.title}
      else empty end
    ] as $possible |
    {sha256: $file.sha256, paths: ($copies | map({path, modified,
      relative_path: (.path | ltrimstr($brainstorming_root + "/"))})),
     new_since_last_scan: ([$old_files[] | select(.sha256 == $file.sha256)] | length == 0),
     ignored: (($ignored_hashes | index($file.sha256)) != null),
     library_matches: ($exact + $possible)}
  )) as $files |
  {scanned_at: $scanned_at, brainstorming_root: $brainstorming_root,
   first_scan: ($previous[0].scanned_at? == null),
   source_pdf_count: ($sources | length), unique_pdf_count: ($files | length),
   files: $files,
   candidates: [$files[] | select((.library_matches | length) == 0 and (.ignored | not))],
   possible_library_matches: [$files[] | select(
     (.ignored | not) and (.library_matches | length) > 0 and
     ([.library_matches[] | select(.reason == "sha256")] | length) == 0)]}
' > "$scratch_dir/report.json"

jq -e 'type == "object" and (.files | type == "array")' "$scratch_dir/report.json" >/dev/null
mv -- "$scratch_dir/report.json" "$watch_dir/report.json"
jq -r '
  "# Brainstorming 待确认 PDF", "",
  "扫描时间（UTC）：\(.scanned_at)。修改时间使用 Asia/Hong_Kong 时区，不代表文件存入时间。", "",
  "共扫描 \(.source_pdf_count) 个 PDF；当前有 \(.candidates | length) 个文件内容尚未匹配库中记录。文件名和标题匹配仍需核验；本清单不代表全部都是新发表或刚存入的论文。", "",
  "仅检查时，请回复全部、编号或暂不入库；已要求入库或解析时，按该请求继续处理。", "",
  "| 编号 | 相对 Brainstorming 的路径 | 修改时间 |", "| --- | --- | --- |",
  (.candidates | sort_by(.paths[0].path) | to_entries[] |
   "| \(.key + 1) | `\(.value.paths[0].relative_path | gsub("\\|"; "&#124;"))` | \(.value.paths[0].modified[0:19]) |")
' "$watch_dir/report.json" > "$scratch_dir/candidates.md"
mv -- "$scratch_dir/candidates.md" "$watch_dir/candidates.md"
jq '{scanned_at, brainstorming_root, first_scan, source_pdf_count, unique_pdf_count,
     candidate_count: (.candidates | length),
     possible_library_match_count: (.possible_library_matches | length)}' "$watch_dir/report.json"
