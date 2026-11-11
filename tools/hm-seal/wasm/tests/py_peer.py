"""The Python side of the interop test: a phone that talks to the WebAssembly device.

python py_peer.py start DIR   reads DIR/web.kp; creates the group, adds the web
                              device, seals a message and a frame for it
python py_peer.py reply DIR   loads the phone again and opens what the web
                              device sent back (DIR/web.msg, DIR/web.frame)
"""
import pathlib
import sys

import hm_seal

step, d = sys.argv[1], pathlib.Path(sys.argv[2])

if step == "start":
    phone = hm_seal.Member(b"phone")
    phone.create_group(b"account-1")
    _commit, welcome = phone.add((d / "web.kp").read_bytes())
    (d / "py.welcome").write_bytes(welcome)
    (d / "py.msg").write_bytes(phone.seal(b"from python"))
    (d / "py.frame").write_bytes(phone.frame_sealer().seal(b"frame from python", b"meta"))
    (d / "phone.save").write_bytes(phone.save())
elif step == "reply":
    phone = hm_seal.Member.load((d / "phone.save").read_bytes())
    kind, sender, data = phone.handle((d / "web.msg").read_bytes())
    opener = hm_seal.FrameOpener()
    phone.update_opener(opener)
    frame = opener.open((d / "web.frame").read_bytes(), b"meta")
    print(f"{kind} {sender} {data.decode()} | {frame.decode()}")
else:
    sys.exit(f"unknown step {step}")
