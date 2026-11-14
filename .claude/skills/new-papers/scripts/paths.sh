#!/usr/bin/env bash

select_brainstorming_root() {
  local candidate
  local available=()
  if [[ -n "${SCHOLARAIO_BRAINSTORMING_ROOT:-}" ]]; then
    [[ -d "$SCHOLARAIO_BRAINSTORMING_ROOT" ]] || {
      echo "Cannot access directory: $SCHOLARAIO_BRAINSTORMING_ROOT" >&2
      return 1
    }
    (cd -- "$SCHOLARAIO_BRAINSTORMING_ROOT" && pwd -P)
    return
  fi
  if [[ $# == 0 ]]; then
    set -- /mnt/e/Study/Brainstorming /mnt/c/Study/Brainstorming
  fi
  for candidate in "$@"; do
    [[ ! -d "$candidate" ]] || available+=("$candidate")
  done
  if [[ ${#available[@]} != 1 ]]; then
    echo "Expected one Brainstorming directory; found ${#available[@]}. Set SCHOLARAIO_BRAINSTORMING_ROOT to choose the source." >&2
    return 1
  fi
  (cd -- "${available[0]}" && pwd -P)
}
