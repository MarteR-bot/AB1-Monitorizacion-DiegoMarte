#--Assigment Brief Parte 1: Monitorizacion con n8n--

#1. Gemelo Digital que calcule la memoria RAM, CPU, SWAP y temperatura de nuestro ordenador en tiempo real
#2. Enviarselo a n8n

import psutil #libreria: https://psutil.readthedocs.io/stable/
import sys
import requests
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from collections import deque
import time

#configuracion
TOKEN = "biqyVo40SCIGjdQg2lJL2_Up4y_SOCdsB2aoxQdGzhi5L5GFTM8ZggGsrR1Eofkn_6qJiDhrltH985uHJ1-r_Q==" #pon tu token de influxdb aqui
ORG = "MSMK"
BUCKET = "Memoria_RAM"
URL = "http://localhost:8086"

#n8n
N8N_WEBHOOK = "http://localhost:5678/webhook-test/monitor"  #webhook URL para test
#N8N_WEBHOOK = "http://localhost:5678/webhook/monitor" #webhook URL para produce

lecturas = deque(maxlen=5)  # 20 lecturas x 3 s = 1 minuto
lecturas_cpu = deque(maxlen=5)

#conexion
client = InfluxDBClient(url=URL, token=TOKEN, org=ORG)
write_api = client.write_api(write_options=SYNCHRONOUS)


def bytes_to_GB(valor_bytes):
    """
    Convierte los bytes a Gigabytes
    """
    return round(valor_bytes / 1024**3, 2)

def barra(porcentaje, ancho=20):
    llenos = int(porcentaje / 100 * ancho)
    return "█" * llenos + "░" * (ancho - llenos)


virtual_memory = psutil.virtual_memory()
print("Conectado, a InfluxDB. Enviando Datos")
print("\nRAM Total:", bytes_to_GB(virtual_memory.total),"Gb")
print("\n")

try:
    while True:
        # memoria RAM
        virtual_memory = psutil.virtual_memory()
        
        #temperatura
        temperatura = None
        if hasattr(psutil, "sensors_temperatures"):
            sensores = psutil.sensors_temperatures(fahrenheit=False)
            valores = []
            for nombre, lista in sensores.items():
                for t in lista:
                    valores.append(t.current)
                if valores:
                    temperatura = max(valores)
        #SWAP
        virtual_swap = psutil.swap_memory()

        # CPU
        cpu_por_nucleo = psutil.cpu_percent(interval= 1, percpu=True)
       
        cpu_total = round(sum(cpu_por_nucleo) / len(cpu_por_nucleo), 1)
        

        #Procesos
        procesos = sorted(psutil.process_iter(['name', 'memory_percent', 'username']),
                    key=lambda p: p.info['memory_percent'] or 0, reverse=True)[:5]


        #lista de diccionarios con los procesos
        lista_procesos = []
        for p in procesos:
            lista_procesos.append({
                "nombre": p.info['name'],
                "ram_porcentaje": round(p.info['memory_percent'] or 0, 1),
                "usuario": p.info['username']
            })

        dato= Point("ordenador_personal") \
        .tag("id", "MacBook_Diego") \
        .field("MemoriaUsadaGB", bytes_to_GB(virtual_memory.used)) \
        .field("MemoriaTotalGB", bytes_to_GB(virtual_memory.total)) \
        .field("MemoriaPorcentaje", virtual_memory.percent) \
        .field("CPU_Total",cpu_total) \
        .field("SWAPUsadaGB", bytes_to_GB(virtual_swap.used) ) \
        .field("SWAPPorcentaje", virtual_swap.percent) \
        .time(time.time_ns(), WritePrecision.NS)

        #field por cada nucleo
        for i, valor in enumerate(cpu_por_nucleo):
            dato.field(f"CPU_Nucleo_{i}", valor)

        #la temperatura se añade solo si existe, en Mac (mi ordenador) sera None
        if temperatura is not None:
            dato.field("Temperatura", temperatura)

        # enviar dato
        try:
            write_api.write(bucket=BUCKET, org=ORG, record=dato)
        except Exception as e:
            print(f"Error enviando datos a InfluxDB: {e}")

        
        #Print RAM, CPU, Temperatura, SWAP, y Procesos
        print("=" * 60)
        print(f" Lectura {time.strftime('%H:%M:%S')}  |  Equipo: MacBook_Diego") #si lo vas a hacer con tu equipo solo cambia el nombre
        print("=" * 60)
        

        print("\n Memoria RAM")
        print(f"   Usada : {bytes_to_GB(virtual_memory.used)} GB de {bytes_to_GB(virtual_memory.total)} GB")
        print(f"   Uso   : [{barra(virtual_memory.percent)}] {virtual_memory.percent:5.1f}%")

        print("\n SWAP")
        print(f"   Usada : {bytes_to_GB(virtual_swap.used)} GB de {bytes_to_GB(virtual_swap.total)} GB")
        print(f"   Uso   : [{barra(virtual_swap.percent)}] {virtual_swap.percent:5.1f}%")

        print("\n CPU")
        print(f"   Total : [{barra(cpu_total)}] {cpu_total:5.1f}%")
        for i, valor in enumerate(cpu_por_nucleo):
            print(f"   Nº {i}   : [{barra(valor, 10)}] {valor:5.1f}%")

        print("\n Temperatura")
        if temperatura is not None:
            print(f"   {temperatura} °C")
        else:
            print("   No disponible en este sistema")
        

        print("\n TOP 5 Procesos (por RAM)")
        print(f"   {'Nombre':<35} {'RAM':>6}  Usuario")
        print("   " + "-" * 55)
        for p in lista_procesos:
            nombre = (p['nombre'] or "?")[:35]
            ram = p['ram_porcentaje'] or 0
            print(f"   {nombre:<35} {ram:5.1f}%  {p['usuario']}")


        lecturas.append(virtual_memory.percent)
        lecturas_cpu.append(cpu_total)

        if len(lecturas) == lecturas.maxlen:
            media = sum(lecturas) / len(lecturas)
            media_cpu = sum(lecturas_cpu) / len(lecturas_cpu)
            print("\n ENVIO A n8n")
            print(f"   Media RAM: {media:.1f}% | Media CPU: {media_cpu:.1f}%")
            try:
                respuesta = requests.post(N8N_WEBHOOK, json={
                    "mediaRAM": round(media, 1),
                    "mediaCPU": round(media_cpu, 1),
                    "SwapPorcentaje": virtual_swap.percent,
                    "temperatura": temperatura,
                    "procesos": lista_procesos
                    }, timeout=5)
                respuesta.raise_for_status()
                print(f"   Estado: enviado correctamente (HTTP {respuesta.status_code})")
            except requests.RequestException as e:
                print("   Estado: Error ->", e)
            lecturas.clear()  # evita mandar la alerta en cada ciclo
            lecturas_cpu.clear()
        
        print("------------------------------------------------------")
        
        # 3 segundos entre lecturas
        time.sleep(3)

except KeyboardInterrupt:
    print("\n Simulación detenida por el usuario.")

finally:
    client.close()