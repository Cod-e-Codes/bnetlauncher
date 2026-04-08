"""
bnetlauncher — Battle.net launcher for Linux.
Entry point: configures Wayland environment before GTK loads.
"""
import os
import sys


def setup_environment() -> None:
    """
    Configure environment variables for Wayland-native GTK4 operation.
    Must be called before importing gi/GTK so GDK picks them up.
    """
    # Prefer Wayland backend; fall back to X11 (XWayland) if unavailable.
    # Setting both lets GTK try Wayland first without hard-failing.
    if "GDK_BACKEND" not in os.environ:
        os.environ["GDK_BACKEND"] = "wayland,x11"

    # Wayland compositor hint: request client-side decorations off on GNOME
    os.environ.setdefault("GTK_CSD", "1")

    # Ensure XDG_RUNTIME_DIR is set (required for Wayland sockets)
    if "XDG_RUNTIME_DIR" not in os.environ and hasattr(os, "getuid"):
        uid = os.getuid()
        xdg = f"/run/user/{uid}"
        if os.path.isdir(xdg):
            os.environ["XDG_RUNTIME_DIR"] = xdg

    # Make XWayland display discoverable for Wine child processes.
    # XWayland typically attaches to :0 unless another compositor claimed it.
    # We probe for an active socket rather than hard-coding.
    if "DISPLAY" not in os.environ:
        for n in range(10):
            sock = f"/tmp/.X11-unix/X{n}"
            if os.path.exists(sock):
                os.environ["DISPLAY"] = f":{n}"
                break

    # Tell Qt apps (in case any helper uses Qt) to also use Wayland
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland;xcb")
    os.environ.setdefault("QT_WAYLAND_DISABLE_WINDOWDECORATION", "1")


def main() -> int:
    setup_environment()

    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
    except (ImportError, ValueError) as e:
        print(
            f"ERROR: Missing dependencies: {e}\n"
            "Install: python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1",
            file=sys.stderr,
        )
        return 1

    from bnetlauncher.app import BNetApplication

    app = BNetApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
