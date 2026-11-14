# -*- coding: utf-8 -*-
"""
diagnostico_desempenho.py
Lê (sem mudar nada) o que pesa no desempenho do FortiGate 60D (FortiOS 5.4.10): DNS, interfaces, regras (UTM,
registro de tráfego, offload, modelador), modeladores e o uso de CPU e memória. Também olha o PC: IPv6, Tailscale,
o Wi-Fi (o que a placa aceita e os canais em volta). Nenhuma senha, MAC ou número de série vai para a saída.

Uso:  python scripts\\diagnostico_desempenho.py            (FortiGate e PC)
      python scripts\\diagnostico_desempenho.py --so-pc
"""
import argparse
import json
import subprocess
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

CHAVES_REGRA = ("policyid", "name", "srcintf", "dstintf", "action", "nat", "utm-status", "logtraffic",
                "auto-asic-offload", "traffic-shaper", "traffic-shaper-reverse", "per-ip-shaper", "inspection-mode",
                "tcp-session-without-syn", "status")
CHAVES_INTERFACE = ("name", "mode", "ip", "mtu-override", "mtu", "speed", "role", "type", "estimated-upstream-bandwidth",
                    "estimated-downstream-bandwidth", "inbandwidth", "outbandwidth", "device-identification", "status")
CHAVES_GLOBAL = ("hostname", "admin-https-redirect", "tcp-halfopen-timer", "tcp-timewait-timer", "udp-idle-timer",
                 "check-protocol-header", "anti-replay", "fortiextender", "wireless-controller", "gui-device-latitude",
                 "batch-cmdb", "max-dlpstat-memory", "memory-use-threshold-red", "proxy-worker-count",
                 "scanunit-count", "sslvpn-max-worker-count", "traffic-priority", "traffic-priority-level")


def _nome(v):
    if isinstance(v, list):
        return ",".join(str(x.get("name", x)) if isinstance(x, dict) else str(x) for x in v)
    return v


def _so(dic, chaves):
    return {k: _nome(dic[k]) for k in chaves if k in dic}


def fortigate():
    from fortigate_api import FortiAPI
    from provisionar_fortigate import ENV, ler_env
    env = ler_env(ENV)
    api = FortiAPI(env.get("FORTIGATE_IP", "10.0.20.1"), env.get("FORTIGATE_CERT_SHA256") or None, timeout=20)
    api.login("admin", env["ADMIN_SENHA"])
    saida = {}
    try:
        def ler(caminho):
            try:
                r = api.ler(caminho)
                return r if isinstance(r, list) else [r]
            except Exception as e:      # noqa: BLE001 - so leitura: o que falhar vira texto
                return [{"erro": str(e)[:100]}]
        saida["dns"] = _so(ler("system/dns")[0], ("primary", "secondary", "domain", "dns-cache-limit",
                                                  "dns-cache-ttl", "cache-notfound-responses", "source-ip"))
        saida["global"] = _so(ler("system/global")[0], CHAVES_GLOBAL)
        saida["interfaces"] = [_so(i, CHAVES_INTERFACE) for i in ler("system/interface")
                               if i.get("name") in ("wan1", "wan2", "internal", "internal2", "dmz")]
        saida["regras"] = [_so(r, CHAVES_REGRA) for r in ler("firewall/policy")]
        saida["modeladores"] = ler("firewall.shaper/traffic-shaper")
        saida["modeladores_por_ip"] = ler("firewall.shaper/per-ip-shaper")
        saida["dns_servidor"] = ler("system/dns-server")
        saida["log_memoria"] = ler("log.memory/setting")
        saida["log_disco"] = ler("log.disk/setting")
        try:
            saida["recursos"] = api.monitor("system/resource")
        except Exception as e:          # noqa: BLE001
            saida["recursos"] = str(e)[:100]
    finally:
        try:
            api.logout()
        except Exception:               # noqa: BLE001
            pass
    return saida


def ps(cmd):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.stdout.strip()


def pc():
    return {
        "ipv6_global": ps("Get-NetIPAddress -AddressFamily IPv6 | Where-Object { $_.PrefixOrigin -in 'RouterAdvertisement','Dhcp' -and $_.IPAddress -notlike 'fe80*' } | ForEach-Object { $_.InterfaceAlias + ' ' + $_.PrefixOrigin }"),
        "tailscale": ps("(Get-Command tailscale -ErrorAction SilentlyContinue).Source; Get-Service Tailscale -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Status"),
        "adaptadores": ps("Get-NetAdapter | Where-Object Status -eq 'Up' | ForEach-Object { $_.Name + ' | ' + $_.InterfaceDescription + ' | ' + $_.LinkSpeed }"),
        "metricas": ps("Get-NetIPInterface -AddressFamily IPv4 | Where-Object ConnectionState -eq 'Connected' | ForEach-Object { $_.InterfaceAlias + ' ' + $_.InterfaceMetric }"),
        "dns_do_pc": ps("Get-DnsClientServerAddress -AddressFamily IPv4 | Where-Object ServerAddresses | ForEach-Object { $_.InterfaceAlias + ' ' + ($_.ServerAddresses -join ',') }"),
        "wifi_driver": ps("netsh wlan show drivers | Select-String 'Hosted network|Rede hospedada|Radio types|Tipos de r|Wi-Fi Direct|Bands|Bandas|Driver  '"),
        "wifi_interface": ps("netsh wlan show interfaces | Select-String 'Channel|Canal|Radio type|Tipo de r|Receive rate|Taxa de recep|Signal|Sinal|Band|Banda'"),
        "redes_em_volta": ps("netsh wlan show networks mode=bssid | Select-String 'Channel|Canal|Signal|Sinal|Band|Banda'"),
        "tcp_global": ps("netsh int tcp show global"),
        "energia": ps("powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE | Select-String 'AC Power|Corrente Alternada|CA'"),
        "rdp": ps("(Get-ItemProperty 'HKLM:\\System\\CurrentControlSet\\Control\\Terminal Server').fDenyTSConnections"),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Lê o que pesa no desempenho, sem mudar nada.")
    ap.add_argument("--so-pc", action="store_true")
    args = ap.parse_args(argv)
    saida = {"pc": pc()}
    if not args.so_pc:
        try:
            saida["fortigate"] = fortigate()
        except Exception as e:          # noqa: BLE001
            saida["fortigate"] = {"erro": str(e)[:200]}
    print(json.dumps(saida, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
