"""layout-fixer: fix text typed in the wrong keyboard layout (us <-> ua).

  layout-fixer daemon            run the background service
  layout-fixer settings          open the settings window
  layout-fixer status | log      what the service is doing / recent decisions (log mode)
  layout-fixer toggle            auto mode on/off
  layout-fixer mode auto|manual|log
  layout-fixer fix-last          fix the last word (or undo the last fix)
  layout-fixer fix-selection     convert the selected text
  layout-fixer reload            re-read the config
  layout-fixer train [--extra FILE[:WEIGHT]]   rebuild the language model
"""

import json
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config


def send(cmd: str) -> dict:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(3)
            s.connect(config.SOCKET_PATH)
            s.sendall((cmd + "\n").encode())
            data = b""
            while chunk := s.recv(65536):
                data += chunk
        return json.loads(data)
    except (OSError, ValueError) as err:
        return {"ok": False, "error": f"service not reachable ({err})"}


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return
    cmd = args[0]
    if cmd == "daemon":
        import daemon
        daemon.run()
    elif cmd == "settings":
        import settings
        settings.main()
    elif cmd == "train":
        import train
        sys.argv = ["train", "--out", os.path.join(config.DATA_DIR, "model.json.gz"), *args[1:]]
        os.makedirs(config.DATA_DIR, exist_ok=True)
        train.main()
        print(send("reload").get("error", "service reloaded"))
    else:
        reply = send(" ".join(args))
        if cmd == "log" and reply.get("ok"):
            print("\n".join(reply["log"]) or "(empty: log mode records decisions here)")
        else:
            print(json.dumps(reply, ensure_ascii=False, indent=2))
        sys.exit(0 if reply.get("ok") else 1)


if __name__ == "__main__":
    main()
