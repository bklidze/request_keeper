import argparse
import grpc
import json
import os
import requests
import sqlite3
import sys
import tempfile
from datetime import datetime
from grpc_tools import protoc
from zeep import Client


def ext_help():  # объявляем функцию, где прописываем собственный текст справки
    print('\n   (?) you must enter the request <url> for REST, SOAP or gRPC.\n\n       options:\n        --method  –  HTTP-method or SOAP-method\n        --data    –  request data (JSON)\n        --params  –  parameters for SOAP-request or gRPC-request\n        --proto   –  URL to .proto file for gRPC\n        --get     –  get response by ID from database\n\n       for example:\n        python client.py https://api.example.com/users\n        python client.py https://service.com/soap?wsdl --method GetUser --params "{\\"id\\": 123}"\n        python client.py grpc://localhost:50051 --method UserService/GetUser --params "{\\"id\\": 123}" --proto https://example.com/service.proto\n        python client.py --get 1')


def init_db():  # создаем базу данных и таблицу, если их нет
    conn = sqlite3.connect('requests.db')  # подключаемся к базе данных
    cursor = conn.cursor()  # создаем курсор
    cursor.execute('CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY AUTOINCREMENT, protocol TEXT NOT NULL, method TEXT NOT NULL, url TEXT NOT NULL, status_code INTEGER, response TEXT, timestamp TEXT NOT NULL)')  # создаем таблицу requests
    conn.commit()  # сохраняем изменения

    return conn  # возвращаем соединение


def save_db(conn, protocol, method, url, status_code, response):  # сохраняем ответ в базу данных
    cursor = conn.cursor()  # создаем курсор
    timestamp = datetime.now().isoformat()  # получаем текущее время
    cursor.execute('INSERT INTO requests (protocol, method, url, status_code, response, timestamp) VALUES (?, ?, ?, ?, ?, ?)', (protocol, method, url, status_code, response, timestamp))  # вставляем данные
    conn.commit()  # сохраняем изменения

    return cursor.lastrowid  # возвращаем ID сохраненной записи


def get_db(conn, request_id):  # получаем ответ из базы данных по ID
    cursor = conn.cursor()  # создаем курсор
    cursor.execute('SELECT * FROM requests WHERE id = ?', (request_id,))  # ищем запись по ID
    row = cursor.fetchone()  # получаем запись
    
    if not row:  # если запись не найдена
        print(f'\n   (!) error: request with that id ({request_id}) not found')  # выводим сообщение об ошибке
        sys.exit(1)  # завершаем выполнение программы с кодом 1

    print(f'\n   id: {row[0]}')
    print(f'\n   url: {row[3]}')
    print(f'   protocol: {row[1]}')
    print(f'   method: {row[2]}')
    print(f'\n   timestamp: {row[6]}')

    if row[4]:
        print(f'   status code: {row[4]}')
    if row[5]:
        response_text = row[5].replace('\n', '\n             ')  # формируем ответ
        print(f'   response: {response_text}')


def parse_args():  # объявляем функцию, где прописываем парсер аргументов командной строки
    parser = argparse.ArgumentParser(usage=argparse.SUPPRESS, add_help=False)  # прописываем парсер
    parser.add_argument('url', nargs="?")  # добавляет позиционный аргумент <url>
    parser.add_argument('--method', default="GET")  # добавляет опциональный аргумент – метод
    parser.add_argument("--data")  # добавляет опциональный аргумент – данные запроса
    parser.add_argument("--params")  # добавляет опциональный аргумент – параметры
    parser.add_argument("--proto")  # добавляет опциональный аргумент – URL к .proto файлу
    parser.add_argument("--get", type=int)  # добавляет опциональный аргумент – ID для получения ответа
    parser.add_argument("-h", "--help", action="store_true")  # добавляет флаг – справка
    args = parser.parse_args()  # объявляем метод, который парсит аргументы командной строки

    if args.help:  # если прописали --help, выводим сообщение со справкой
        ext_help()  # вызываем функцию, где прописан собственный текст справки
        sys.exit(0)  # завершаем выполнение программы с кодом 0
    elif args.get:  # если указали --get, выводим ответ по ID
        conn = init_db()  # подключаемся к базе данных
        get_db(conn, args.get)  # получаем ответ по ID
        conn.close()  # закрываем соединение
        sys.exit(0)  # завершаем выполнение программы с кодом 0
    elif not args.url:  # если url не указали, выводим сообщения об ошибках
        print(' \n   (!) error: <url> is required to make the request.')  # выводим сообщение о том, что необходимо указать url
        print('       about usage: python client.py <url> [--method (METHOD)] [--data (DATA)] [--params (PARAMS)] [--proto (PROTO_URL)]')  # выводим сообщение с инструкцией использования
        sys.exit(1)  # завершаем выполнение программы с кодом 1
    
    return args  # возвращаем распарсенные аргументы


def proto_load(proto_url):  # загрузка .proto файл по ссылке

    try:
        response = requests.get(proto_url, timeout=10)  # скачиваем .proto файл по URL
        response.raise_for_status()  # проверяем статус ответа
        temp_dir = tempfile.mkdtemp()  # создаем временную директорию
        proto_path = os.path.join(temp_dir, 'service.proto')  # путь к .proto файлу
        with open(proto_path, 'w') as f:  # открываем файл для записи
            f.write(response.text)  # записываем содержимое .proto файла
        
        protoc.main([  # генерируем Python-код из .proto файла
            'grpc_tools.protoc',
            f'-I{temp_dir}',
            f'--python_out={temp_dir}',
            f'--grpc_python_out={temp_dir}',
            proto_path
        ])
        sys.path.insert(0, temp_dir)  # добавляем временную директорию в sys.path

        import service_pb2  # импортируем сгенерированный модуль с сообщениями
        import service_pb2_grpc  # импортируем сгенерированный модуль с сервисами
        return service_pb2, service_pb2_grpc, temp_dir  # возвращаем модули
        
    except Exception as e:
        print(f'\n   (!) error: failed to load proto file – {e}')  # выводим сообщение об ошибке
        sys.exit(1)  # завершаем выполнение программы с кодом 1


def grpc_request(url, method, params, proto_url):  # отправка gRPC-запроса

    try:
        target = url.replace('grpc://', '')  # убираем 'grpc://' из URL, получаем только host:port (например, localhost:50051)

        if not proto_url:
            print(f'\n   (!) error: --proto URL is required for gRPC requests')  # если не указан .proto файл, выводим сообщение об ошибке
            sys.exit(1)  # завершаем выполнение программы с кодом 1
        pb2, pb2_grpc = proto_load(proto_url)  # вызываем функцию proto_load, которая скачивает .proto файл и генерирует Python-модули; получаем модуль с сообщениями (pb2) и модуль с сервисами (pb2_grpc)
        channel = grpc.insecure_channel(target)  # создаем незащищенный канал связи с gRPC-сервером по адресу target

        if params:
            params_dict = json.loads(params)  # парсим параметры из JSON
        else:
            params_dict = {}  # если параметров нет, создаем пустой словарь
        service_name, method_name = method.split('/')  # разделяем service_name/method_name
        stub_class = getattr(pb2_grpc, f'{service_name}Stub')  # находим stub-класс для сервиса
        stub = stub_class(channel)  # создаем экземпляр stub, передавая ему канал связи
        grpc_method = getattr(stub, method_name)  # находим метод
        request_class = None  # инициализируем переменную для класса запроса (пока None)
        possible_names = [    # список возможных имен классов запросов в сгенерированном коде
            f'{method_name}Request',  # SayHelloRequest
            f'{method_name}Req',      # SayHelloReq
            f'{method_name}Input',    # SayHelloInput
        ]

        for name in possible_names:  # перебираем возможные имена
            if hasattr(pb2, name):  # проверяем, существует ли такой класс в модуле pb2
                request_class = getattr(pb2, name)
                break  # выходим из цикла
        
        if not request_class:  # если класс не найден по возможным именам
            for attr_name in dir(pb2):  # перебираем все атрибуты модуля pb2
                if 'Request' in attr_name or 'Req' in attr_name or 'Input' in attr_name:# ищем атрибуты, содержащие Request, Req или Input
                    attr = getattr(pb2, attr_name)  # получаем атрибут
                    if isinstance(attr, type): 
                        request_class = attr  # проверяем, является ли атрибут классом, если да, используем его как класс запроса
                        break  # выходим из цикла
        
        if not request_class:
            print(f'\n   (!) error: cannot find request class for method {method_name}')  # выводим сообщение об ошибке
            sys.exit(1)  # завершаем выполнение программы с кодом 1
        
        request = request_class(**params_dict)  # создаем запрос с параметрами
        response = grpc_method(request)  # вызываем метод
        
        return str(response)  # возвращаем ответ как строку
        
    except json.JSONDecodeError:
        print(f'\n   (!) error: invalid JSON params – {params}')  # если ошибка парсинга JSON, выводим сообщение об ошибке
        sys.exit(1)  # завершаем выполнение программы с кодом 1
    except TypeError as e:
        print(f'\n   (!) error: invalid parameters – {e}')  # если ошибка в параметрах, выводим сообщение об ошибке
        sys.exit(1)  # завершаем выполнение программы с кодом 1
    except Exception as e:
        print(f'\n   (!) error: gRPC request failed – {e}')  # если любая из ошибок, выводим сообщение об ошибке
        sys.exit(1)  # завершаем выполнение программы с кодом 1


def soap_request(url, method, params):  # отправка SOAP-запроса

    try:
        client = Client(url)  # создаем SOAP клиент из WSDL
        
        if params:
            params_dict = json.loads(params)  # парсим параметры из JSON
        else:
            params_dict = {}  # если параметров нет, используем пустой словарь
        soap_method = getattr(client.service, method)  # находим метод на сервисе
        response = soap_method(**params_dict)  # вызываем метод с параметрами
        
        return str(response)  # возвращаем ответ как строку
        
    except json.JSONDecodeError:
        print(f'\n   (!) error: invalid JSON params: {params}')  # если ошибка парсинга JSON, выводим сообщение об ошибке
        sys.exit(1)  # завершаем выполнение программы с кодом 1
    except Exception as e:
        print(f'\n   (!) error: SOAP request failed: {e}')  # если любая из ошибок, выводим сообщение об ошибке
        sys.exit(1)  # завершаем выполнение программы с кодом 1


def rest_request(url, method, data):  # отправка REST-протокола

    try:
        if method.upper() == "GET":
            response = requests.get(url, timeout=10)  # если указан метод GET, отправляем GET-запрос с таймаутом в 10 секунд
        elif method.upper() == "POST":
            response = requests.post(url, json=json.loads(data) if data else None, timeout=10)  # если POST-запрос отправляем POST-запрос, парсим JSON если data есть
        elif method.upper() == "PUT":
            response = requests.put(url, json=json.loads(data) if data else None, timeout=10)  # если PUT-запрос отправляем PUT-запрос, парсим JSON если data есть
        elif method.upper() == "DELETE":
            response = requests.delete(url, timeout=10)  # если указан метод DELETE, отправляем DELETE-запрос с таймаутом в 10 секунд
        else:
            print('\n' + f'   (!) error: unsupported HTTP-method: {method}')  # если метод не поддерживается, выводим сообщение об ошибке
            sys.exit(1)  # завершаем выполнение программы с кодом 1
        response.raise_for_status()  # проверяем статус ответа, в некоторых случаях вызываем исключение

        return response  # возвращаем объект ответа
        
    except requests.exceptions.Timeout:
        print(f'\n   (!) error: request timed out')  # если превышено время ожидания, выводим сообщение об ошибке
        sys.exit(1)  # завершаем выполнение программы с кодом 1
    except requests.exceptions.ConnectionError:
        print(f'\n   (!) error: connection failed to {url}')  # если ошибка соединения, выводим сообщение об ошибке
        sys.exit(1)  # завершаем выполнение программы с кодом 1
    except requests.exceptions.HTTPError as e:
        print(f'\n   (!) error: HTTP error – {e}')  # если HTTP-ошибка, выводим сообщение об ошибке
        sys.exit(1)  # завершаем выполнение программы с кодом 1
    except requests.exceptions.RequestException as e:
        print(f'\n   (!) error: {e}')  # если иная ошибка запроса, выводим сообщение об ошибке
        sys.exit(1)  # завершаем выполнение программы с кодом 1
    except json.JSONDecodeError:
        print(f'\n   (!) error: invalid JSON data: {data}')  # если ошибка парсинга JSON, выводим сообщение об ошибке
        sys.exit(1)  # завершаем выполнение программы с кодом 1


def main():  # объявляем функцию, где определяем тип протокола
    args = parse_args()  # объявляем метод, который вызывает парсер аргументов командной строки
    conn = init_db()  # подключаемся к базе данных
    
    if args.url.startswith('grpc://'):  # если аргумент начинается с 'grpc://'  
        protocol = 'gRPC'  # определяем протокол как gRPC
        print(f'\n   protocol: {protocol}')  # прописываем протокол в логе
        print(f'   method: {args.method}')  # прописываем метод в логе
        if args.params:
            print(f'\n   parameters: {args.params}')  # прописываем параметры в логе, если они есть
        if args.proto:
            print(f'   proto: {args.proto}')  # прописываем URL .proto файла в логе, если он есть

        response = grpc_request(args.url, args.method, args.params, args.proto)  # отправляем gRPC-запрос
        print(f'\n   response: {response}')  # прописываем ответ
        
        request_id = save_db(conn, protocol, args.method, args.url, None, response)  # сохраняем в БД
        print(f'\n   responce was saved under id: {request_id}')  # прописываем ID сохраненной записи
        print(f'   to get response, use:   python request_keeper.py --get {request_id}')  # прописываем подсказку

    elif '?wsdl' in args.url.lower():  # если аргумент имеет '?wsdl'
        protocol = 'SOAP'  # определяем протокол как SOAP
        print(f'\n   protocol: {protocol}')  # прописываем протокол в логе
        print(f'   method: {args.method}')  # прописываем метод в логе
        if args.params:
            print(f'   parameters: {args.params}')  # прописываем параметры в логе, если они есть

        response = soap_request(args.url, args.method, args.params)  # отправляем SOAP-запрос
        print(f'\n   response: {response}')  # прописываем ответ
        
        request_id = save_db(conn, protocol, args.method, args.url, None, response)  # сохраняем в БД
        print(f'\n   responce was saved under id: {request_id}')  # прописываем ID сохраненной записи
        print(f'   to get response, use:   python request_keeper.py --get {request_id}')  # прописываем подсказку

    else:  # в остальных случаях 
        protocol = 'REST'  # определяем протокол как REST
        print(f'\n   protocol: {protocol}')  # прописываем протокол в логе
        print(f'   method: {args.method}')  # прописываем метод в логе
        if args.data:
            print(f'   data: {args.data}')  # прописываем данные запроса в логе, если они есть

        response = rest_request(args.url, args.method, args.data)  # отправляем REST-запрос
        print(f'\n   status code: {response.status_code}')  # прописываем статус-код в логе
        response_text = response.text.replace('\n', '\n             ')  # формируем ответ 
        print(f'   response: {response_text}')  # прописываем ответ
        
        request_id = save_db(conn, protocol, args.method, args.url, response.status_code, response.text)  # сохраняем в БД
        print(f'\n   responce was saved under id: {request_id}')  # прописываем ID сохраненной записи
        print(f'   to get response, use:   python request_keeper.py --get {request_id}')  # прописываем подсказку
    
    conn.close()  # закрываем соединение с базой данных


if __name__ == "__main__":
    main()