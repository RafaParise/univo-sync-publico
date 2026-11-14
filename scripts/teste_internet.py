# -*- coding: utf-8 -*-
"""
teste_internet.py - teste de internet do painel "Infraestrutura da casa" (14/11/2026).

Pedido do Rafael: "banda de internet para ser um próprio teste de internet muito mais preciso e confiável".
O que o torna mais confiável que um site de teste comum:
  1. vários fluxos ao mesmo tempo (um só não enche uma fibra de 500 Mbit/s), pelo tempo fixo de 8 s, contando os bytes
     de verdade que chegaram (não uma estimativa);
  2. a latência PARADA e a latência COM CARGA (durante o download e o envio): a diferença é o "bufferbloat", o que faz
     o jogo travar quando alguém baixa algo (13/11: o A12 perdia 31% dos pings com o PC baixando a 468 Mbit/s);
  3. a conferência pelo FortiGate: os contadores da WAN1 no mesmo intervalo. Se o FortiGate vê muito mais tráfego do
     que o teste mediu, outra coisa da rede estava usando a internet (o número do teste não é só da linha);
  4. latência medida com conexão bloqueante (no Windows, a espera com prazo do Python soma ~10 ms a cada medida).
Servidor: speed.cloudflare.com (o mesmo do teste da Cloudflare; grátis, sem conta, nada pessoal vai junto).
Gasta dados: uns 300 a 800 MB por teste numa fibra. Por isso só roda quando alguém pede (tecla T no painel).
A Cloudflare limita testes seguidos: em 14/11/2026, depois de 3 testes em 5 minutos, respondeu 429 ("muitos pedidos")
pedindo ~1 h de espera. Pedidos de 90 MB (o máximo aceito fica abaixo de 100 MB) gastam menos pedidos por teste; se ela
recusar, o resultado diz isso e quanto esperar, em vez de mostrar "0 Mbit/s".
Medido em 14/11/2026, 03h12 (PC no cabo do FortiGate): 610 Mbit/s de download, 465 de envio, latência parada 8,2 ms e
+2 ms com carga.

Uso:  python scripts\\teste_internet.py
"""
import http.client
import socket
import ssl
import statistics
import threading
import time

SERVIDOR = "speed.cloudflare.com"
SEGUNDOS = 8.0
FLUXOS = 4
BLOCO = 1 << 16
TAMANHO = 90_000_000                # cada pedido; a Cloudflare recusa (403) a partir de 100 MB, e limita (429) muitos pedidos seguidos
RECUSAS = []                        # (HTTP, retry-after) das recusas do servidor no teste em curso


def _conexao():
    return http.client.HTTPSConnection(SERVIDOR, timeout=10, context=ssl.create_default_context())


def latencias(host=SERVIDOR, porta=443, vezes=5, intervalo=0.1, parar=None):
    """Milissegundos de cada conexão TCP (bloqueante), até `vezes` ou até `parar` (Event) ligar."""
    valores = []
    endereco = socket.getaddrinfo(host, porta, socket.AF_INET, socket.SOCK_STREAM)[0][4]
    while (parar is None and len(valores) < vezes) or (parar is not None and not parar.is_set()):
        conexao = socket.socket()
        inicio = time.perf_counter()
        try:
            conexao.connect(endereco)
            valores.append((time.perf_counter() - inicio) * 1000)
        except OSError:
            pass
        finally:
            conexao.close()
        time.sleep(intervalo)
    return valores


def _resumo_latencia(valores):
    if not valores:
        return None
    variacao = statistics.mean(abs(a - b) for a, b in zip(valores, valores[1:])) if len(valores) > 1 else 0.0
    return {"min": min(valores), "mediana": statistics.median(valores), "variacao": variacao, "n": len(valores)}


def _fase(trabalho, segundos, fluxos, contadores=None):
    """Roda `trabalho(fim, somar)` em `fluxos` linhas ao mesmo tempo; mede a latência junto.
    Devolve (Mbit/s medidos, latências com carga, Mbit/s que o FortiGate viu ou None)."""
    total, trava = [0], threading.Lock()

    def somar(n):
        with trava:
            total[0] += n
    antes_forti = contadores() if contadores else None
    parar = threading.Event()
    com_carga = []
    medidor = threading.Thread(target=lambda: com_carga.extend(latencias(intervalo=0.25, parar=parar)), daemon=True)
    inicio = time.perf_counter()
    fim = inicio + segundos
    linhas = [threading.Thread(target=trabalho, args=(fim, somar), daemon=True) for _ in range(fluxos)]
    for linha in linhas:
        linha.start()
    time.sleep(0.5)                                  # a latência com carga começa com a linha já cheia
    medidor.start()
    for linha in linhas:
        linha.join(segundos + 15)
    parar.set()
    medidor.join(5)
    gasto = time.perf_counter() - inicio
    depois_forti = contadores() if contadores else None
    visto = None
    if antes_forti and depois_forti:
        visto = tuple((d - a) * 8 / gasto / 1e6 for a, d in zip(antes_forti, depois_forti))
    return total[0] * 8 / gasto / 1e6, com_carga, visto


def _baixar(fim, somar):
    while time.perf_counter() < fim:
        conexao = _conexao()
        try:
            conexao.request("GET", "/__down?bytes=%d" % TAMANHO, headers={"User-Agent": "parise-sync"})
            resposta = conexao.getresponse()
            if resposta.status != 200:           # 429: a Cloudflare limitou; parar este fluxo e contar o motivo
                RECUSAS.append((resposta.status, resposta.getheader("retry-after")))
                return
            while time.perf_counter() < fim:
                pedaco = resposta.read(BLOCO)
                if not pedaco:
                    break
                somar(len(pedaco))
        except (OSError, http.client.HTTPException):
            time.sleep(0.2)
        finally:
            conexao.close()


def _enviar(fim, somar):
    bloco = b"\0" * BLOCO
    while time.perf_counter() < fim:
        conexao = _conexao()
        try:
            conexao.putrequest("POST", "/__up")
            conexao.putheader("User-Agent", "parise-sync")
            conexao.putheader("Content-Type", "application/octet-stream")
            conexao.putheader("Content-Length", str(TAMANHO))
            conexao.endheaders()
            enviados = 0
            while enviados < TAMANHO and time.perf_counter() < fim:
                pedaco = bloco[:TAMANHO - enviados]
                conexao.send(pedaco)
                enviados += len(pedaco)
                somar(len(pedaco))
            if enviados >= TAMANHO:              # pedido completo: lê a resposta e abre outro
                resposta = conexao.getresponse()
                resposta.read()
                if resposta.status != 200:
                    RECUSAS.append((resposta.status, resposta.getheader("retry-after")))
                    return
        except (OSError, http.client.HTTPException):
            time.sleep(0.2)
        finally:
            conexao.close()


def medir(contadores_da_wan=None, segundos=SEGUNDOS, fluxos=FLUXOS, aviso=None):
    """O teste inteiro. `contadores_da_wan()` devolve (bytes que entraram, bytes que saíram) da WAN1 do FortiGate,
    ou None. `aviso(texto)` recebe o andamento. Devolve um dict com tudo (ou {"erro": ...})."""
    aviso = aviso or (lambda _t: None)
    del RECUSAS[:]
    try:
        aviso("latência parada...")
        parada = _resumo_latencia(latencias(vezes=8))
        aviso("download (%d fluxos, %d s)..." % (fluxos, segundos))
        baixa, lat_baixando, visto_baixando = _fase(_baixar, segundos, fluxos, contadores_da_wan)
        aviso("envio (%d fluxos, %d s)..." % (fluxos, segundos))
        sobe, lat_enviando, visto_enviando = _fase(_enviar, segundos, fluxos, contadores_da_wan)
    except (OSError, socket.gaierror) as falha:
        return {"erro": "sem internet ou sem o servidor de teste (%s)" % falha}
    if RECUSAS and (baixa < 1 or sobe < 1):
        status, espera = RECUSAS[0]
        minutos = (" em uns %d min" % max(1, int(espera) // 60)) if str(espera or "").isdigit() else " mais tarde"
        return {"erro": "a Cloudflare recusou (HTTP %s%s): limite de testes seguidos; tente de novo%s" % (
            status, ", muitos pedidos" if status == 429 else "", minutos)}
    return {"quando": time.strftime("%H:%M:%S"), "download": baixa, "envio": sobe, "parada": parada,
            "baixando": _resumo_latencia(lat_baixando), "enviando": _resumo_latencia(lat_enviando),
            "forti_baixando": visto_baixando[0] if visto_baixando else None,
            "forti_enviando": visto_enviando[1] if visto_enviando else None}


def linhas(r):
    """O resultado em frases curtas, para o painel e para o terminal."""
    if not r:
        return []
    if r.get("erro"):
        return ["⛔ Teste de internet: %s" % r["erro"]]
    p, b, e = r.get("parada"), r.get("baixando"), r.get("enviando")
    saida = ["Teste de internet das %s (Cloudflare, %d fluxos):" % (r["quando"], FLUXOS),
             "   download %6.0f Mbit/s   envio %6.0f Mbit/s" % (r["download"], r["envio"])]
    if p:
        saida.append("   latência parada %.1f ms (variação %.1f ms)" % (p["mediana"], p["variacao"]))
    if p and b and e:
        piora = max(b["mediana"], e["mediana"]) - p["mediana"]
        nota = ("ótima para jogar" if piora < 15 else "boa" if piora < 40 else
                "ruim: o jogo trava quando alguém baixa algo")
        saida.append("   com carga: baixando %.0f ms, enviando %.0f ms (+%.0f ms: %s)" % (
            b["mediana"], e["mediana"], piora, nota))
    if r.get("forti_baixando") is not None:
        saida.append("   o FortiGate viu na WAN1: %.0f Mbit/s entrando e %.0f Mbit/s saindo" % (
            r["forti_baixando"], r["forti_enviando"] or 0))
    return saida


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    print("\n".join(linhas(medir(aviso=lambda t: print("  " + t)))))
