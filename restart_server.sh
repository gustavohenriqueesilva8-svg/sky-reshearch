#!/usr/bin/env bash
set -euo pipefail

PORT=8002
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LISTENERS="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN || true)"
PIDS=""

if [[ -n "$LISTENERS" ]]; then
  for pid in $LISTENERS; do
    command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    process_cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | awk 'substr($0, 1, 1) == "n" && !found { value = substr($0, 2); found = 1 } END { if (found) print value }')"
    process_executable="$(lsof -a -p "$pid" -d txt -Fn 2>/dev/null | awk 'substr($0, 1, 1) == "n" && !found { value = substr($0, 2); found = 1 } END { if (found) print value }')"
    case "$command_line" in
      *"$ROOT/app.py"*|*"$ROOT/teste.py"*|*"/Downloads/teste.py"*|*"uvicorn app:app"*)
        PIDS="${PIDS:+$PIDS }$pid"
        ;;
      *)
        # Em alguns ambientes o macOS nega ps ao sandbox. Se o processo
        # estiver no diretório do projeto e for o Python do sistema, aceite
        # a identificação do dono do projeto (o servidor usa `python app.py`).
        if [[ "$process_cwd" == "$ROOT" && "$process_executable" == */Python.app/Contents/MacOS/Python ]]; then
          PIDS="${PIDS:+$PIDS }$pid"
        else
          echo "A porta $PORT está ocupada por um processo não reconhecido: PID $pid" >&2
          echo "$command_line" >&2
          echo "Diretório: ${process_cwd:-desconhecido}; executável: ${process_executable:-desconhecido}" >&2
          exit 1
        fi
        ;;
    esac
  done
fi

for pid in $PIDS; do
  echo "Encerrando o backend PID $pid na porta $PORT..."
  kill -TERM "$pid" 2>/dev/null || true
  for attempt in {1..30}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      break
    fi
    sleep 0.1
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "PID $pid não encerrou após SIGTERM; enviando SIGKILL."
    kill -KILL "$pid"
  fi
done

if lsof -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "A porta $PORT continua ocupada após o encerramento." >&2
  exit 1
fi

if [[ -n "${PYTHON_BIN:-}" ]]; then
  if [[ -x "$PYTHON_BIN" ]]; then
    PYTHON="$PYTHON_BIN"
  elif command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    PYTHON="$(command -v "$PYTHON_BIN")"
  else
    echo "Python não encontrado em PYTHON_BIN: $PYTHON_BIN" >&2
    exit 1
  fi
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
elif [[ -x "$HOME/Downloads/.venv/bin/python" ]]; then
  PYTHON="$HOME/Downloads/.venv/bin/python"
else
  PYTHON="$(command -v python3 || true)"
fi

if [[ -z "$PYTHON" || ! -x "$PYTHON" ]]; then
  echo "Python não encontrado. Defina PYTHON_BIN com o executável desejado." >&2
  exit 1
fi

cd "$ROOT"
echo "Iniciando o backend do projeto em 127.0.0.1:$PORT..."
exec "$PYTHON" app.py
