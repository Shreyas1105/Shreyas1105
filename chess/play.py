#!/usr/bin/env python3
"""Community chess vs Stockfish, driven by GitHub Issues.

Security notes:
- Issue title/author arrive via environment variables (never interpolated
  into shell), and are validated against strict regexes.
- A move is only applied if python-chess says it is legal in the current
  position, so arbitrary input can never alter state beyond a legal move.
"""
import json
import os
import random
import re
import shutil
from pathlib import Path
from urllib.parse import quote

import chess
import chess.engine
import chess.svg

ROOT = Path(__file__).resolve().parent.parent
GAME = ROOT / "chess" / "game.json"
BOARD_SVG = ROOT / "chess" / "board.svg"
README = ROOT / "README.md"

REPO = os.environ.get("REPO", "Shreyas1105/Shreyas1105")
BRANCH = os.environ.get("BRANCH", "main")
OWNER = os.environ.get("OWNER", "")
TITLE = os.environ.get("ISSUE_TITLE", "")
USER = os.environ.get("ISSUE_USER", "")
COMMENT_FILE = Path(os.environ.get("COMMENT_FILE", "/tmp/chess-comment.md"))

MOVE_RE = re.compile(r"^chess\|move\|([a-h][1-8][a-h][1-8][qrbn]?)$")
USER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
SKILL_LEVEL = 5  # Stockfish 0-20. Low enough that visitors can win.
MARK_START, MARK_END = "<!-- CHESS:START -->", "<!-- CHESS:END -->"


def new_state(players=None, games=1):
    return {
        "fen": chess.STARTING_FEN,
        "history": [],
        "last_uci": None,
        "result": None,
        "players": players or {},
        "games": games,
    }


def load():
    if GAME.exists():
        return json.loads(GAME.read_text())
    return new_state()


def save(state):
    GAME.parent.mkdir(parents=True, exist_ok=True)
    GAME.write_text(json.dumps(state, indent=2) + "\n")


def outcome_text(board):
    outcome = board.outcome(claim_draw=True)
    if outcome is None:
        return None
    if outcome.winner is True:
        return "Visitors win! \U0001F389"
    if outcome.winner is False:
        return "Stockfish wins."
    return "Draw (" + outcome.termination.name.lower().replace("_", " ") + ")"


def engine_move(board):
    path = shutil.which("stockfish") or "/usr/games/stockfish"
    if os.path.exists(path):
        try:
            with chess.engine.SimpleEngine.popen_uci(path) as eng:
                try:
                    eng.configure({"Skill Level": SKILL_LEVEL})
                except chess.engine.EngineError:
                    pass
                return eng.play(board, chess.engine.Limit(time=0.3)).move
        except (chess.engine.EngineError, OSError):
            pass
    return random.choice(list(board.legal_moves))  # fallback if no engine


def render_board(state, board):
    lastmove = chess.Move.from_uci(state["last_uci"]) if state["last_uci"] else None
    svg = chess.svg.board(
        board,
        lastmove=lastmove,
        size=360,
        coordinates=True,
        colors={
            "square light": "#ebecd0",
            "square dark": "#739552",
            "square light lastmove": "#f5f682",
            "square dark lastmove": "#b9ca43",
            "margin": "#262421",
            "coord": "#f5f5f5",
        },
    )
    BOARD_SVG.write_text(svg)


def issue_link(title, label):
    t = quote(title, safe="")
    b = quote("Just click 'Submit new issue'. Don't edit the title.", safe="")
    return f"[{label}](https://github.com/{REPO}/issues/new?title={t}&body={b})"


def render_section(state, board):
    img = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/chess/board.svg?v={len(state['history'])}"
    lines = [f'<p align="center"><img src="{img}" width="360" alt="Current chess position"/></p>', ""]

    if state["result"]:
        lines.append(f"**Game over: {state['result']}** · {issue_link('chess|new', 'Start a new game')}")
    else:
        lines.append(
            "**Your move.** You play White \u2659 and I (Stockfish, intentionally easy) reply as Black \u265F. "
            "Click a move below, then press *Submit new issue*."
        )
        moves = sorted((board.san(m), m.uci()) for m in board.legal_moves)
        links = " \u00B7 ".join(issue_link(f"chess|move|{uci}", san) for san, uci in moves)
        lines += ["", "<details><summary>Legal moves</summary>", "", links, "", "</details>"]

    recent = state["history"][-6:][::-1]
    if recent:
        lines += ["", "**Recent moves**", ""]
        for h in recent:
            piece = "\u2659" if h["side"] == "white" else "\u265F"
            who = h["by"] if h["by"] in ("Stockfish", "anonymous") else f"[@{h['by']}](https://github.com/{h['by']})"
            lines.append(f"- {piece} `{h['san']}` by {who}")

    top = sorted(((u, n) for u, n in state["players"].items() if u != "anonymous"), key=lambda kv: -kv[1])[:5]
    if top:
        board_txt = " \u00B7 ".join(f"[@{u}](https://github.com/{u}) ({n})" for u, n in top)
        lines += ["", f"**Top players:** {board_txt}"]

    lines += ["", f"<sub>Game #{state['games']} \u00B7 powered by GitHub Issues + Actions + python-chess + Stockfish \u00B7 inputs are strictly validated</sub>"]
    return "\n".join(lines)


def update_readme(section):
    text = README.read_text()
    if MARK_START not in text or MARK_END not in text:
        raise SystemExit("README markers missing: add <!-- CHESS:START --> and <!-- CHESS:END -->")
    pattern = re.compile(re.escape(MARK_START) + r".*?" + re.escape(MARK_END), re.S)
    new = f"{MARK_START}\n{section}\n{MARK_END}"
    README.write_text(pattern.sub(lambda _m: new, text))


def write_comment(msg):
    COMMENT_FILE.write_text(msg + "\n")


def set_output(changed):
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")


def main():
    state = load()
    changed = False
    by = USER if USER_RE.match(USER) else "anonymous"

    if not TITLE:  # manual run: (re)build board + README
        changed = True
    elif TITLE == "chess|new":
        if state["result"] or (OWNER and USER == OWNER):
            state = new_state(state["players"], state["games"] + 1)
            changed = True
            write_comment("\u267B\uFE0F New game started. White to move!")
        else:
            write_comment("A game is still in progress. Only the repo owner can restart it early.")
    else:
        m = MOVE_RE.match(TITLE)
        if not m:
            write_comment("\u274C That doesn't look like a move. Use the links in the README.")
        elif state["result"]:
            write_comment("This game is over. Start a new one from the README.")
        else:
            board = chess.Board(state["fen"])
            try:
                move = chess.Move.from_uci(m.group(1))
            except ValueError:
                move = None
            if move is None or move not in board.legal_moves:
                write_comment(f"\u274C `{m.group(1)}` isn't a legal move in this position.")
            else:
                san = board.san(move)
                board.push(move)
                state["history"].append({"side": "white", "san": san, "by": by})
                state["players"][by] = state["players"].get(by, 0) + 1
                state["last_uci"] = move.uci()
                result = outcome_text(board)
                reply = None
                if not result:
                    em = engine_move(board)
                    reply = board.san(em)
                    board.push(em)
                    state["history"].append({"side": "black", "san": reply, "by": "Stockfish"})
                    state["last_uci"] = em.uci()
                    result = outcome_text(board)
                state["fen"] = board.fen()
                state["result"] = result
                changed = True
                msg = f"\u2659 @{by} played **{san}**."
                if reply:
                    msg += f" Stockfish replied **{reply}**."
                if result:
                    msg += f"\n\n**Game over: {result}**"
                write_comment(msg + "\n\nThe README board updates in a few seconds.")

    if changed:
        board = chess.Board(state["fen"])
        save(state)
        render_board(state, board)
        update_readme(render_section(state, board))
    set_output(changed)


if __name__ == "__main__":
    main()
