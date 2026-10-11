#!/usr/bin/env bash
# Generates the role wallets of docs/setup.md section 5 into the repository's .env (git-ignored).
# Only empty <ROLE>_PK slots are filled, so re-running never replaces a key. Private keys are
# written to .env and never printed: copy them to the team password manager from the file.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$ROOT/.env"
ROLES=(DEPLOYER RELAYER ROUTER_SIGNER VERIFIER_SIGNER ANALYST_SIGNER GUARDIAN EU_CASP GH_VASP ATTACKER)

command -v cast >/dev/null || { echo "cast not found: install Foundry (docs/setup.md section 1)" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq not found: brew install jq" >&2; exit 1; }

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$ROOT/.env.example" "$ENV_FILE"
  echo "Created .env from .env.example"
fi
chmod 600 "$ENV_FILE"
git -C "$ROOT" check-ignore -q "$ENV_FILE" || { echo ".env is not git-ignored: refusing to write keys" >&2; exit 1; }

get_var() {
  sed -nE "s/^$1=([^[:space:]#]*).*/\1/p" "$ENV_FILE" | tail -n 1
}

# The value travels through the environment, not the command line, so it never shows in `ps`.
set_var() {
  local name="$1"
  if grep -qE "^$name=" "$ENV_FILE"; then
    VAR_NAME="$name" awk '
      BEGIN { name = ENVIRON["VAR_NAME"]; value = ENVIRON["VAR_VALUE"] }
      index($0, name "=") == 1 { print name "=" value; next }
      { print }
    ' "$ENV_FILE" > "$ENV_FILE.tmp"
    mv "$ENV_FILE.tmp" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
  else
    printf '%s=%s\n' "$name" "$VAR_VALUE" >> "$ENV_FILE"
  fi
}

printf '%-16s %-44s %s\n' ROLE ADDRESS STATE
for role in "${ROLES[@]}"; do
  if [[ -z "$(get_var "${role}_PK")" ]]; then
    wallet="$(cast wallet new --json)"
    VAR_VALUE="$(jq -r '.data[0].private_key' <<<"$wallet")" set_var "${role}_PK"
    address="$(jq -r '.data[0].address' <<<"$wallet")"
    unset wallet
    VAR_VALUE="$address" set_var "${role}_ADDRESS"
    state=new
  else
    address="$(get_var "${role}_ADDRESS")"
    if [[ -z "$address" ]]; then
      address="$(cast wallet address --private-key "$(get_var "${role}_PK")")"
      VAR_VALUE="$address" set_var "${role}_ADDRESS"
    fi
    state=kept
  fi
  printf '%-16s %-44s %s\n' "$role" "$address" "$state"
done

echo
echo "Keys are in .env only. Store each one in the team password manager; never paste a key in a chat."
echo "Next: request test AVAX for the DEPLOYER address, then run contracts/script/fund-wallets.sh."
