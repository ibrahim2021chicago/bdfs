from bofautils.tacmd import Tacmd

def test_tacmd():
    print("=== Testing HUB Login ===")
    tacmd_client = Tacmd()
    hub_login_out, hub_login_err = tacmd_client.login()
    print("HUB login output:", hub_login_out)
    print("HUB login error:", hub_login_err)

    rc, out = tacmd_client.command("listSystems")
    print("HUB command return code:", rc)
    print("HUB command output:", out)

    print("\n=== Testing TEPS Login ===")
    tacmd_client.teps()  # switch to TEPS mode
    teps_login_out, teps_login_err = tacmd_client.login()
    print("TEPS login output:", teps_login_out)
    print("TEPS login error:", teps_login_err)

    rc2, out2 = tacmd_client.command("viewAgent -t NT")
    print("TEPS command return code:", rc2)
    print("TEPS command output:", out2)

if __name__ == "__main__":
    test_tacmd()
