# unpackPy

[![downloads](https://www.python.org/static/img/python-logo.png)](https://www.python.org/downloads/)

## Миссия инструмента

1. Организация процесса сборки/извлечения метаданных:

    - Извелечение исходников, в формате 1С:Предприятие
    - Реорганизция исходников в установленый формат хранения ("unpackPy" формат)
    - Модификация исходников установленного формата
    - Конвертация исходников установленного формата в формат 1С:Предприятие
    - Сборка исполняемых файлов

2. Оптимизация процесса сборки/извлечения метаданных

## Для работы необходима платформа версии 8.3.10 + или хз какая в которой появился формат выгрузки 2.0

## Быстрый старт

1. Установить [python](https://www.python.org/downloads/)
2. Запустить терминал в корневом каталоге репозитория
3. Установить зависимости (от имени администратора)

    ```cmd
    py -m pip install -r ./tools/requirements.txt
    ```

4. Описание утилиты

    ```cmd
    py .\src\v8unpack.py -h
    ```

5. Примеры выполнения команд:

- Разобрать обработку:

```cmd
py .\src\v8unpack.py --v8unpack=./tools/v8unpack.exe parse --epf=./tools/anyEpf.epf --xml=./execution/epfSrc/anyEpf.xml
```

- Разобрать все обработки в каталоге:

```cmd
py .\src\v8unpack.py --v8unpack=./tools/v8unpack.exe parse-all --path=./tools/ --repo-root=./execution/
```

- Собрать обработку:

```cmd
py .\src\v8unpack.py --v8unpack=./tools/v8unpack.exe build --epf=./tools/anyEpf.epf --xml=./execution/epfSrc/anyEpf.xml
```

- Выполнить прекоммит:

```cmd
py .\src\v8unpack.py --v8unpack=./tools/v8unpack.exe precommit --path=.
```

## Проблемы

1. Изменить инструмент таким образом, что бы его было легко внедрить на конкретном продукте
2. Продумать процесс ручного объединения обычных форм
    > Конфликт возникший в обычной форме затруднительно устранить, необходимо предоставить такую возможность при помощи внешнего инструмента. Например: собрать 2 ветки -> устранить в конфигураторе -> разобрать на исходники

## Образец внедрения

```py
import v8unpack

epf = '../src/My.epf'
xml = '../src/My.xml'
unp = '../.git/hooks/v8unpack.exe'
v8unpack.unpack(epf, xml, unp)
v8unpack.build(xml, epf, unp)
```
