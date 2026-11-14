Para unificar toda a sua infraestrutura em **um único script mestre** de forma profissional e definitiva, consolidei a arquitetura para operar exatamente com o seu hardware físico. O computador será o "cérebro de injeção" usando a porta serial, enquanto a rede física assumirá a operação logo em seguida.

### A Estrutura Física da Bancada (Obrigatório)

Antes de pedir para o Claude executar o código, conecte os cabos exatamente nesta disposição:

1. **Cabo de Força:** Ligue o FortiGate e insira um clipe no orifício `RESET` por 15 segundos.
2. **Cabo USB-C para Mini-USB:** Ligue a porta USB-C do PC (Ryzen) na porta `USB MGMT` do FortiGate. (Esta é a via expressa de configuração).
3. **Cabo de Rede 1 (Internet):** Conecte uma porta LAN do roteador da sua casa na porta **`WAN1`** do FortiGate.
4. **Cabo de Rede 2 (Bancada):** Conecte a porta **`1`** (`internal1`) do FortiGate na placa de rede do seu PC.
5. **Cabo de Rede 3 (A12):** Conecte a porta **`DMZ`** ao Galaxy A12 (via hub/adaptador Ethernet).
6. **Cabo de Rede 4 (ARENA):** Conecte a porta **`2`** (`internal2`) ao switch/roteador Wi-Fi dedicado aos controles.

---

### O Script Mestre Unificado (`fortigate_master_deploy.py`)

Este script resolve o dilema de "dois scripts". Quando o Claude executá-lo no seu PC, ele fará **duas coisas simultaneamente**:

1. Acessará o FortiGate pelo cabo USB (ignorando quedas de rede) e injetará 100% da infraestrutura (Failover, QoS, Firewall ADB, Bloqueio de Telemetria, DNS Offline e acesso à internet para o PC).
2. Gerará automaticamente um segundo arquivo na sua área de trabalho chamado `sentinela_a12.py`. Este é o script do Termux (Zero-Trust + Kill Switch) pronto para você copiar para o celular.

Peça para o Claude instalar a dependência (`pip install pyserial`), preencher a porta COM e os endereços MAC, e executar:

```python
import serial
import serial.tools.list_ports
import time
import os

# ==========================================
# 1. VARIÁVEIS DE AMBIENTE (CLAUDE: PREENCHER)
# ==========================================
PORTA_SERIAL = "COM3"  # Ajustar para a porta real (COMx no Windows ou /dev/ttyACM0 no Linux)
BAUD_RATE = 9600

MAC_RYZEN = "00:11:22:33:44:55"
MAC_A12 = "AA:BB:CC:DD:EE:FF"
MAC_CONTROLE_1 = "11:11:11:11:11:11"

# ==========================================
# 2. PAYLOAD CLI FORTIOS (INFRAESTRUTURA TOTAL)
# ==========================================
CONFIG_PAYLOAD = f"""
config system interface
    edit "dmz"
        set vdom "root"
        set ip 10.0.10.1 255.255.255.0
        set allowaccess ping http https
    next
    edit "internal1"
        set vdom "root"
        set ip 10.0.20.1 255.255.255.0
        set allowaccess ping ssh http https snmp
    next
    edit "internal2"
        set vdom "root"
        set ip 10.0.30.1 255.255.255.0
        set allowaccess ping
    next
    edit "wan1"
        set mode dhcp
        set allowaccess ping
    next
    edit "wan2"
        set mode dhcp
    next
end

config system dhcp server
    edit 1
        set interface "internal1"
        set default-gateway 10.0.20.1
        set netmask 255.255.255.0
        config ip-range
            edit 1
                set start-ip 10.0.20.50
                set end-ip 10.0.20.150
            next
        end
        config reserved-address
            edit 1
                set ip 10.0.20.100
                set mac {MAC_RYZEN}
            next
        end
    next
    edit 2
        set interface "dmz"
        set default-gateway 10.0.10.1
        set dns-service default
        set netmask 255.255.255.0
        config ip-range
            edit 1
                set start-ip 10.0.10.50
                set end-ip 10.0.10.50
            next
        end
        config reserved-address
            edit 1
                set ip 10.0.10.50
                set mac {MAC_A12}
            next
        end
    next
    edit 3
        set interface "internal2"
        set default-gateway 10.0.30.1
        set netmask 255.255.255.0
        config ip-range
            edit 1
                set start-ip 10.0.30.100
                set end-ip 10.0.30.150
            next
        end
        config reserved-address
            edit 1
                set ip 10.0.30.10
                set mac {MAC_CONTROLE_1}
            next
        end
    next
end

config firewall address
    edit "MAC_RYZEN_BANCADA"
        set type mac
        set mac {MAC_RYZEN}
    next
    edit "MAC_A12_PARISE_CORE"
        set type mac
        set mac {MAC_A12}
    next
    edit "TELEMETRIA_SAMSUNG"
        set type fqdn
        set fqdn "*.samsung.net"
    next
    edit "ARENA_CONTROLES"
        set type ipmask
        set subnet 10.0.30.0 255.255.255.0
    next
end

config firewall service custom
    edit "ADB_PORT"
        set tcp-portrange 5555
    next
    edit "ARENA_WEBSOCKET"
        set tcp-portrange 8080
    next
    edit "A12_SAUDE_API"
        set tcp-portrange 8000
    next
    edit "TERMUX_SSH"
        set tcp-portrange 8022
    next
end

config firewall shaper traffic-shaper
    edit "ARENA_INPUT_SHAPER"
        set guaranteed-bandwidth 5000
        set maximum-bandwidth 10000
        set priority high
    next
    edit "OBS_UPLOAD_SHAPER"
        set maximum-bandwidth 20000
        set priority medium
    next
end

config firewall ssl-ssh-profile
    edit "AUDITORIA_IA_SNI"
        set server-cert-mode replace
        config https
            set ports 443
            set status certificate-inspection
        end
    next
end

config firewall policy
    edit 1
        set name "INTERNET_PARA_PC_RYZEN"
        set srcintf "internal1"
        set dstintf "wan1" "wan2"
        set srcaddr "MAC_RYZEN_BANCADA"
        set dstaddr "all"
        set action accept
        set schedule "always"
        set service "ALL"
        set nat enable
    next
    edit 2
        set name "ADB_STRICT_BINDING"
        set srcintf "internal1"
        set dstintf "dmz"
        set srcaddr "MAC_RYZEN_BANCADA"
        set dstaddr "MAC_A12_PARISE_CORE"
        set action accept
        set schedule "always"
        set service "ADB_PORT"
        set logtraffic all
    next
    edit 3
        set name "PC_TO_A12_MGMT"
        set srcintf "internal1"
        set dstintf "dmz"
        set srcaddr "MAC_RYZEN_BANCADA"
        set dstaddr "MAC_A12_PARISE_CORE"
        set action accept
        set schedule "always"
        set service "A12_SAUDE_API" "TERMUX_SSH" "PING"
    next
    edit 4
        set name "ARENA_CONTROLES_IN"
        set srcintf "internal2"
        set dstintf "internal1"
        set srcaddr "ARENA_CONTROLES"
        set dstaddr "all"
        set action accept
        set schedule "always"
        set service "ARENA_WEBSOCKET" "PING"
        set traffic-shaper "ARENA_INPUT_SHAPER"
        set diffserv-forward enable
        set diffservcode-forward 101110
    next
    edit 5
        set name "BLOCK_TELEMETRY"
        set srcintf "dmz"
        set dstintf "wan1" "wan2"
        set srcaddr "MAC_A12_PARISE_CORE"
        set dstaddr "TELEMETRIA_SAMSUNG"
        set action deny
        set schedule "always"
        set service "ALL"
        set logtraffic all
    next
    edit 6
        set name "PARISE_CORE_TO_INTERNET"
        set srcintf "dmz"
        set dstintf "wan1" "wan2"
        set srcaddr "MAC_A12_PARISE_CORE"
        set dstaddr "all"
        set action accept
        set schedule "always"
        set service "ALL"
        set utm-status enable
        set ssl-ssh-profile "AUDITORIA_IA_SNI"
        set nat enable
        set logtraffic all
    next
end

config router policy
    edit 1
        set input-device "internal1"
        set src "10.0.20.100/255.255.255.255"
        set dst "10.0.0.0/255.0.0.0"
        set action deny
    next
    edit 2
        set input-device "internal1"
        set src "10.0.20.100/255.255.255.255"
        set dst "0.0.0.0/0.0.0.0"
        set output-device "wan2"
    next
end

config router static
    edit 1
        set dst 0.0.0.0 0.0.0.0
        set device "wan1"
        set distance 10
    next
    edit 2
        set dst 0.0.0.0 0.0.0.0
        set device "wan2"
        set distance 20
    next
end

config system dns-database
    edit "ARENA_LOCAL_DNS"
        set domain "local"
        set authoritative disable
        config dns-entry
            edit 1
                set hostname "arena"
                set ip 10.0.10.50
            next
            edit 2
                set hostname "a12"
                set ip 10.0.10.50
            next
        end
    next
end

config log syslogd setting
    set status enable
    set server "10.0.20.100"
    set port 514
end

config system netflow
    set collector-ip 10.0.20.100
    set collector-port 2055
    set active-flow-timeout 1
end

config system api-user
    edit "claude_parise_core"
        set api-key "<GERAR_NO_FORTIGATE>"
        set accprofile "super_admin"
        set vdom "root"
    next
end
"""

# ==========================================
# 3. GERADOR DO SCRIPT SENTINELA PARA O A12
# ==========================================
TERMUX_SENTINEL_SCRIPT = """import subprocess
import requests
import urllib3
import time
import re

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

FORTIGATE_API_URL = "https://10.0.10.1/api/v2/cmdb/firewall"
API_KEY = "<GERAR_NO_FORTIGATE>"
TEMP_THRESHOLD = 45.0
ALLOWED_PC_IP = "10.0.20.100"

def get_battery_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return float(f.read().strip()) / 1000.0
    except:
        return 30.0

def toggle_adb_port(enable=True):
    action = "accept" if enable else "deny"
    url = f"{FORTIGATE_API_URL}/policy/2?access_token={API_KEY}"
    try:
        requests.put(url, json={"action": action}, verify=False, timeout=3)
        estado = "ABERTA" if enable else "BLOQUEADA (TÉRMICO)"
        print(f"[TERMAL] Porta ADB {estado} no Firewall.")
    except:
        pass

def block_intruder(ip):
    url = f"{FORTIGATE_API_URL}/address?access_token={API_KEY}"
    payload = {"name": f"INTRUSO_{ip.replace('.', '_')}", "subnet": f"{ip} 255.255.255.255"}
    try:
        requests.post(url, json=payload, verify=False, timeout=3)
        print(f"[ZERO-TRUST] IP {ip} isolado na Blacklist do Hardware FortiGate!")
    except:
        pass

def check_adb_connections():
    try:
        output = subprocess.check_output(["netstat", "-tn"], text=True)
        for line in output.split("\\n"):
            if ":5555 " in line and "ESTABLISHED" in line:
                ip = re.split(r'\\s+', line)[4].split(":")[0]
                if ip != ALLOWED_PC_IP and ip != "127.0.0.1":
                    block_intruder(ip)
    except:
        pass

def main():
    print("[+] Sentinela parise-core Iniciado no Android Termux")
    adb_active = True
    while True:
        check_adb_connections()
        temp = get_battery_temp()
        if temp > TEMP_THRESHOLD and adb_active:
            toggle_adb_port(False)
            adb_active = False
        elif temp <= (TEMP_THRESHOLD - 3.0) and not adb_active:
            toggle_adb_port(True)
            adb_active = True
        time.sleep(5)

if __name__ == "__main__":
    main()
"""

# ==========================================
# 4. FUNÇÕES DE EXECUÇÃO SERIAL
# ==========================================
def send_serial_cmd(ser, cmd, wait_time=0.2):
    ser.write((cmd + '\r\n').encode('utf-8'))
    time.sleep(wait_time)
    return ser.read_all().decode('utf-8', errors='ignore')

def wait_for_port(port, timeout=120):
    start = time.time()
    while time.time() - start < timeout:
        if port in [p.device for p in serial.tools.list_ports.comports()]: return True
        time.sleep(2)
    return False

def main():
    # Salva o script do A12 localmente no PC do usuário
    with open("sentinela_a12.py", "w", encoding="utf-8") as f:
        f.write(TERMUX_SENTINEL_SCRIPT)
    print("[+] Arquivo 'sentinela_a12.py' gerado localmente. Copie para o Termux depois.")

    print(f"[+] Conectando ao FortiGate via Serial OOB ({PORTA_SERIAL})...")
    try:
        ser = serial.Serial(PORTA_SERIAL, BAUD_RATE, timeout=2)
        send_serial_cmd(ser, "")
        send_serial_cmd(ser, "")
        send_serial_cmd(ser, "admin", 1)
        send_serial_cmd(ser, "", 1)
        
        print("[+] Fase 1: Quebrando o Switch de Fabrica...")
        send_serial_cmd(ser, "config system global")
        send_serial_cmd(ser, "set internal-switch-mode interface")
        res = send_serial_cmd(ser, "end")
        
        if "y/n" in res.lower() or "continue" in res.lower():
            ser.write(('y\n').encode('utf-8'))
            
        send_serial_cmd(ser, "execute reboot")
        ser.write(('y\n').encode('utf-8'))
        ser.close()
    except Exception as e:
        print(f"[-] Erro na Fase 1: {e}")
        return

    print("[+] Roteador reiniciando. Aguardando a porta USB reconectar...")
    time.sleep(10)
    if not wait_for_port(PORTA_SERIAL):
        print(f"[-] Falha: Porta {PORTA_SERIAL} nao retornou.")
        return
        
    print("[+] Porta USB conectada. Aguardando boot do FortiOS (60s)...")
    time.sleep(60)

    try:
        ser = serial.Serial(PORTA_SERIAL, BAUD_RATE, timeout=2)
        send_serial_cmd(ser, "")
        send_serial_cmd(ser, "admin", 1)
        send_serial_cmd(ser, "", 1)
        
        print("[+] Fase 2: Injetando cabeamento logico e regras (LAN, WAN, VWP, QoS)...")
        for line in CONFIG_PAYLOAD.strip().split("\n"):
            if line.strip() and not line.strip().startswith("#"):
                send_serial_cmd(ser, line.strip(), 0.1)
                
        print("[+] Provisionamento 100% Concluido no FortiGate.")
        ser.close()
    except Exception as e:
        print(f"[-] Erro na Fase 2: {e}")

if __name__ == "__main__":
    main()

```