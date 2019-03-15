import argparse
import binascii
import codecs
import itertools
import os
import shutil
import tempfile
from distutils.dir_util import copy_tree
import uuid
import subprocess
import pathlib
from multiprocessing import Pool
from multiprocessing.dummy import Pool as ThreadPool

import pandas

##########################################
#
# Платформа
#
#########################################


class EnterpriseManager:

    def __init__(self, version=None):

        self._Versions = []
        self._VersionsBinPath = {}
        self._getAllVersions()

        try:
            self._Versions.index(version)
        except ValueError:
            if version is not None:
                error = f'Указанная версия платформы не найдена: {version}'
                raise ValueError(error)
            if len(self._Versions) != 0:
                self.Version = self._Versions[-1]
            else:
                raise RuntimeError(f'Платформа 1С:Предприятие не найдена')
        else:
            self.Version = version

        self.BinPath = self._VersionsBinPath.get(self.Version)

    def _sortVersions(self, version):

        versionList = version.split('.')
        versionInt = ''

        for i in range(len(versionList)):
            value = versionList[i]
            while len(value) < 5:
                value = '0' + value
            versionInt = versionInt + value

        return int(versionInt)

    def _getAllVersions(self):

        pf = []
        pf.append(os.environ.get('PROGRAMFILES(x86)',
                                 'C:/Program Files (x86)'))
        pf.append(os.environ.get('PROGRAMFILES',
                                 'C:/Program Files'))

        for pfPath in pf:
            v8 = os.path.join(pfPath, '1cv8')
            if not os.path.exists(v8):
                continue
            for dirname in os.listdir(v8):
                # Проверка формата
                dirList = dirname.split('.')
                if len(dirList) != 4:
                    continue
                # Проверка значений
                try:
                    for i in range(4):
                        int(dirList[i])
                except ValueError:
                    continue
                else:
                    # мы не перетераем данные полученные ранее,
                    # таким образом приоритет отдается х86-32 платформе
                    if self._Versions.count(dirname) != 0:
                        continue
                    self._Versions.append(dirname)
                    self._VersionsBinPath[dirname] = os.path.join(v8,
                                                                  dirname,
                                                                  'bin',
                                                                  '1cv8.exe')

        self._Versions.sort(key=self._sortVersions)

    def epfDump(self, epf, xml):

        # Подготовка окружения

        with tempfile.TemporaryDirectory() as tempdir:
            INFOBASE = self.createTempFileDB(tempdir)
            LOGDESIGNER = os.path.join(tempdir,
                                       'DESIGNER.LOG')
            LOGDump = os.path.join(tempdir,
                                   'DumpExternalDataProcessorOrReportToFiles.LOG')
            formatDump = 'Hierarchical'

            # Удаление предполагаемых исходников

            root = os.path.normpath(self.getEpfDumpRoot(xml))
            if os.path.exists(xml):
                os.remove(xml)
            if os.path.exists(root):
                shutil.rmtree(root, ignore_errors=True)

            # Выгрузка обработки в файлы

            Enterprise = os.path.normpath(self.BinPath)
            INFOBASE = os.path.normpath(INFOBASE)
            LOGDESIGNER = os.path.normpath(LOGDESIGNER)
            xml = os.path.normpath(xml)
            epf = os.path.normpath(epf)
            LOGDump = os.path.normpath(LOGDump)

            cmdStr = f'""{Enterprise}" ' +\
                     f'DESIGNER /F "{INFOBASE}" /Out "{LOGDESIGNER}" ' +\
                '/WA+ /DisableStartupMessages /DisableStartupDialogs /DumpExternalDataProcessorOrReportToFiles ' +\
                f'"{xml}" "{epf}" -Format {formatDump} /Out "{LOGDump}""'

            result = os.system(cmdStr)

            # Исключения

            if os.path.exists(LOGDump):
                logtext = open(LOGDump, 'r').read()
            else:
                logtext = ''

            if result != 0:
                raise Exception(f'''Не удалось выгрузить обработку в файлы \n
                                 Подробности: {logtext}''')
            else:
                if logtext.find('формата потока') != -1:
                    raise Exception(logtext)

    def epfBuid(self, xml, epf):

        with tempfile.TemporaryDirectory() as tempdir:
            INFOBASE = self.createTempFileDB(tempdir)
            LOGDESIGNER = tempdir + '/DESIGNER.LOG'
            LOGLoad = tempdir + '/LoadExternalDataProcessorOrReportFromFiles.LOG'

            # Загрузка обработки из файлов

            cmdStr = f'""{self.BinPath}" DESIGNER /F "{INFOBASE}" /Out "{LOGDESIGNER}" ' + \
                '/WA+ /DisableStartupMessages /DisableStartupDialogs ' + \
                '/LoadExternalDataProcessorOrReportFromFiles ' + \
                f'"{os.path.normpath(xml)}" "{os.path.normpath(epf)}" ' + \
                f'/Out "{LOGLoad}""'

            result = os.system(cmdStr)

            # Исключения

            if os.path.exists(LOGLoad):
                logtext = open(LOGLoad, 'r').read()
            else:
                logtext = ''

            if result != 0:
                raise Exception(f'''Не удалось выгрузить обработку в файлы \n
                                 Подробности: {logtext}''')
            else:
                if logtext.find('формата потока') != -1:
                    raise Exception(logtext)

    def getEpfDumpRoot(self, xml):

        basename = os.path.basename(xml)
        root = os.path.join(
            os.path.dirname(xml),
            os.path.splitext(basename)[0])
        return root

    def createTempFileDB(self, tempdir):

        INFOBASE = os.path.normpath(tempdir)
        LOG = os.path.normpath(tempdir + '/CREATEINFOBASE.LOG')

        # Создание информационной базы

        cmdStr = f'""{self.BinPath}" ' + \
                 f'CREATEINFOBASE File="{INFOBASE}" /Out "{LOG}""'
        result = os.system(cmdStr)

        if result != 0:
            logtext = ''
            if os.path.exists(LOG):
                logtext = open(LOG, 'r').read()
            raise EnvironmentError(f'''Не удалось создать информационную базу \n
                                    Подробности: {logtext}''')

        return INFOBASE

##########################################
#
# ПАРСЕР ФОРМЫ
#
#########################################


class Form:

    def __init__(self, formDataPath):
        self._formDataPath = formDataPath
        self._formDatalines = []
        self._formDataRows = []
        self._formDataTree = None
        self._formDatalevel = 0
        self._allformDataArray = []

    def _branch(self, parent=None):

        formDataArray = []

        branch = {
            'rows': formDataArray,
            'parent': parent
        }

        self._allformDataArray.append(formDataArray)

        return branch

    def _readRows(self, rowNumber):

        line = self._formDatalines[rowNumber]
        line = line.replace('\n', '')
        line = line.replace('\r', '')
        line = line.replace('\t', '')

        if line == '':
            return

        rowData = self._readLine(line)

        self._formDataRows[rowNumber] = rowData

    def _readLine(self, line):

        tree = self._branch()
        lastBranch = self._formDataLineToTree(line, tree)

        rowData = {
            'branch': tree,
            'lastBranch': lastBranch,
            'openTag': line[0] == '{',
            'lastPropertyTag': line[-1] != ','
        }

        return rowData

    def _formDataLineToTree(self, line, tree):

        i = len(line)

        for symbol in reversed(line):

            if symbol == '}':

                newBranch = self._branch(tree)
                newline = line[0:i-1]
                lastBranch = self._formDataLineToTree(newline, newBranch)

                self._appendRow(tree['rows'], newBranch)
                return lastBranch

            elif symbol == '{':
                return tree
            elif symbol == ',':
                tree['rows'].append(None)
            else:
                self._setRow(tree['rows'], symbol)

            i = i-1

        return tree

    def _appendRow(self, rows, row):

        if len(rows) == 0:
            rows.append(row)
        elif rows[-1] is None:
            rows[-1] = row
        else:
            rows.append(row)

    def _setRow(self, rows, value):

        if len(rows) == 0:
            rows.append(value)
        elif rows[-1] is None:
            rows[-1] = value
        else:
            rows[-1] = rows[-1] + value

    def _buildTree(self):

        currentBranch = self._formDataRows[-1]['lastBranch']['parent']

        for dataRow in reversed(self._formDataRows):

            if dataRow is None:
                continue

            if id(self._formDataRows[-1]) == id(dataRow):
                continue

            # Запись

            dataRow['branch']['parent'] = currentBranch
            for row in dataRow['branch']['rows']:
                if type(row) == dict:
                    row['parent'] = currentBranch
                currentBranch['rows'].append(row)

            # Выбор новой текущей позиции

            newCurrentBranch = dataRow['lastBranch']

            if (newCurrentBranch is None or
                    dataRow['lastBranch'] == dataRow['branch']):

                newCurrentBranch = currentBranch

            if dataRow['openTag']:

                newCurrentBranch = newCurrentBranch['parent']

            currentBranch = newCurrentBranch

        # Инвертируем результат

        for array in self._allformDataArray:
            array.reverse()
            for i in range(len(array)):
                if type(array[i]) == str:
                    array[i] = array[i][::-1]

        if currentBranch is None:
            # Исключение для чтения "красивого формата"
            # т.к. читалка говно и формат говно
            # то и исключение говно
            self._formDataTree = dataRow['lastBranch']['parent']
            del self._formDataTree['rows'][-1]
        else:
            self._formDataTree = currentBranch['rows'][0]

    def _findInFormDataArray(self, value):

        result = []

        for i in range(len(self._allformDataArray)):
            array = self._allformDataArray[i]
            for j in range(len(array)):
                if array[j] == value:
                    try:
                        index = result.index(i)
                    except ValueError:
                        index = None
                    if index is None:
                        result.append(i)
                    break

        return result

    def _findFormDataArrayByID(self, valueid):

        for i in range(len(self._allformDataArray)):
            array = self._allformDataArray[i]
            if id(array) == valueid:
                return array

        return None

    def _removeShitFromControlPanel(self, address):

        ControlPanelData = self._allformDataArray[address]
        if len(ControlPanelData) == 2:
            return

        # Изменяется какая-то шляпа, диагностировано на EDI

        if ControlPanelData[0] == 'e69bf21d-97b2-4f37-86db-675aea9ec2cb':
            ControlPanelName = ControlPanelData[4]['rows'][1]
            ControlPanelName = ControlPanelName.replace('"', '')
            newUUID = uuid.uuid5(uuid.NAMESPACE_DNS, ControlPanelName)
            ControlPanelData[2]['rows'][1]['rows'][-4] = str(newUUID)

        # Прочитаем командную панель во что-то

        ControlPanel = formPanel(ControlPanelData)
        if ControlPanel is None:
            return
        if len(ControlPanel['itemParameters']) == 0:
            return

        itemsDataArray = self._findFormDataArrayByID(
            ControlPanel['itemsDataId']
        )

        # Сгенерируем новые ID

        itemsID = {}
        for item in ControlPanel['items']:
            index = ControlPanel['items'].index(item)
            itemKey = item['name'] + "_" + str(index)
            UUID = uuid.uuid5(uuid.NAMESPACE_DNS, itemKey)
            item['newID'] = str(UUID)
            item['index'] = index
            itemsID[item['id']] = item

        # Подготовка к сортировке

        for parm in ControlPanel['itemParameters']:
            item = itemsID[parm['id']]
            parm['newID'] = item['newID']
            parm['branch'] = itemsDataArray[parm['index']]
            parm['itemindex'] = item['index']
            parm['itemGroupDataId'] = item['groupDataId']
            parm['itemGroupDataIdIndex'] = item['groupDataIdIndex']

        itemParams = pandas.DataFrame(ControlPanel['itemParameters'])
        itemParamsSorted = itemParams.sort_values('itemindex').to_dict('r')

        # Перестановка и изменение UUID

        i = -1
        begin = ControlPanel['itemParameters'][0]['index']
        end = ControlPanel['itemParameters'][-1]['index']
        for j in range(begin, end + 1):

            i = i + 1
            paramDataId = itemParamsSorted[i]['dataid']
            paramNewUUID = itemParamsSorted[i]['newID']
            paramBranch = itemParamsSorted[i]['branch']
            itemGroupDataId = itemParamsSorted[i]['itemGroupDataId']
            itemGroupDataIdIndex = itemParamsSorted[i]['itemGroupDataIdIndex']

            # изменение UUID

            paramDataArray = self._findFormDataArrayByID(paramDataId)
            paramDataArray[1] = paramNewUUID
            itemGroupDataArray = self._findFormDataArrayByID(itemGroupDataId)
            itemGroupDataArray[itemGroupDataIdIndex] = paramNewUUID

            # Перестановка

            itemsDataArray[j] = paramBranch

    def _writeBranch(self, branch, file):

        if self._formDataTree == branch:
            file.write('{')
        else:
            file.write('\r\n{')

        countOfRow = len(branch['rows'])
        isBase64 = False

        if countOfRow > 0:
            firstRow = branch['rows'][0]
            if type(firstRow) == str and firstRow[0:8] == '#base64:':
                isBase64 = True

        for i in range(countOfRow):

            if i != 0 and i != countOfRow and not isBase64:
                file.write(',')

            row = branch['rows'][i]
            if type(row) == dict:
                self._writeBranch(row, file)
            elif isBase64:
                self._formDatalevel = 0
                file.write(row)
                if i != countOfRow - 1:
                    file.write('\r\r\n')
            else:
                self._formDatalevel = 0
                file.write(row)

        if self._formDatalevel == 1:
            self._formDatalevel = 0
            file.write('\r\n')

        file.write('}')
        self._formDatalevel = 1

    def _writeBranchPretty(self, branch, file):

        self._formDatalevel = self._formDatalevel + 1

        otst = ''

        for i in range(self._formDatalevel):
            if i != 0:
                otst = otst + '\t'

        if self._formDataTree == branch:
            file.write(otst+'{')
        else:
            file.write('\r\n'+otst+'{')

        countOfRow = len(branch['rows'])
        isBase64 = False

        if countOfRow > 0:
            firstRow = branch['rows'][0]
            if type(firstRow) == str and firstRow[0:8] == '#base64:':
                isBase64 = True

        for i in range(countOfRow):

            row = branch['rows'][i]
            if type(row) == dict:
                self._writeBranchPretty(row, file)
                if i != countOfRow - 1:
                    file.write(',')
            elif isBase64:
                if i == 0:
                    file.write('\r\n'+otst+'\t')
                file.write(row)
            else:
                file.write('\r\n'+otst+'\t')
                file.write(row)
                if i != countOfRow - 1:
                    file.write(',')

        file.write('\r\n'+otst+'}')

        self._formDatalevel = self._formDatalevel - 1

    def read(self):

        # Чтение строк данных формы в ветки

        file = codecs.open(self._formDataPath, 'r', encoding='utf-8-sig')

        self._formDatalines = file.readlines()
        self._formDataRows = [None] * len(self._formDatalines)

        with ThreadPool() as pool:
            pool.map(self._readRows, range(len(self._formDatalines)))

        # Объединение веток

        self._buildTree()

    def removeShit(self):

        # Какое-то говно итерируется при каждом пересохранении

        Shit1 = self._formDataTree['rows'][1]['rows']
        Shit1[10] = '1'

        # e69bf21d-97b2-4f37-86db-675aea9ec2c - командная панель

        ControlPanelInDataArray = self._findInFormDataArray(
            'e69bf21d-97b2-4f37-86db-675aea9ec2cb'
        )
        for address in ControlPanelInDataArray:
            self._removeShitFromControlPanel(address)

        # 6ff79819-710e-4145-97cd-1618da79e3e2 - кнопка в режим меню

        ControlPanelInDataArray = self._findInFormDataArray(
            '6ff79819-710e-4145-97cd-1618da79e3e2'
        )
        for address in ControlPanelInDataArray:
            self._removeShitFromControlPanel(address)

    def write(self, fileName):

        file = codecs.open(fileName, 'w+', 'utf-8-sig')
        self._formDatalevel = 0
        self._writeBranch(self._formDataTree, file)

    def writePretty(self, fileName):
        file = codecs.open(fileName, 'w+', 'utf-8-sig')
        self._formDatalevel = -1
        self._writeBranchPretty(self._formDataTree, file)


def formPanel(data):

    controlPanel = {}

    # Параметры элементов формы
    itemParameters = []
    items = []

    # Инициализация объекта
    # Неупорядоченая коллекция

    if data[0] == 'e69bf21d-97b2-4f37-86db-675aea9ec2cb':
        itemsData = data[2]['rows'][1]['rows'][7]['rows']
    elif data[0] == '6ff79819-710e-4145-97cd-1618da79e3e2':
        MenuMode = data[2]['rows'][1]['rows'][11]
        if MenuMode == '0':
            return
        itemsData = data[2]['rows'][1]['rows'][12]['rows']
    else:
        raise IOError('что ты мне суешь?')

    itemsParamCount = int(itemsData[4])
    for i in range(5, 5 + itemsParamCount):
        itemsParamData = itemsData[i]['rows']
        itemsParam = {}
        itemsParam['id'] = itemsParamData[1]
        itemsParam['dataid'] = id(itemsParamData)
        itemsParam['index'] = i

        itemParameters.append(itemsParam)

    # Упорядоченая коллекция
    itemsGroup = []
    itemsGroupCount = int(itemsData[5 + itemsParamCount])
    for i in range(6 + itemsParamCount, 6 + itemsParamCount + itemsGroupCount):
        itemsGroup.append(itemsData[i])

    # Заполнение массив элементов
    for itemGroup in itemsGroup:

        itemGroupData = itemGroup['rows']
        itemsCount = int(itemGroupData[4])
        for i in range(5, 5 + itemsCount * 2, 2):
            item = {}
            item['id'] = itemGroupData[i]
            item['name'] = itemGroupData[i+1]['rows'][1]
            item['name'] = item['name'].replace('"', '')
            item['dataid'] = id(itemGroupData[i+1]['rows'])

            item['groupDataId'] = id(itemGroupData)
            item['groupDataIdIndex'] = i

            items.append(item)

    controlPanel['itemsDataId'] = id(itemsData)
    controlPanel['items'] = items
    controlPanel['itemParameters'] = itemParameters

    return controlPanel

##########################################
#
# Сборка разборка
#
#########################################


def unpackForms(formpath, v8unpackpath):

    v8unpackpath = os.path.normpath(v8unpackpath)
    formpath = os.path.normpath(formpath)
    formdir = os.path.dirname(formpath)

    сmdStr = f'""{v8unpackpath}" -U "{formpath}" "{formdir}""'
    result = os.system(сmdStr)

    if result != 0:
        Exception(f'Не удалось разобрать форму {formpath}')

    return result


def afterUnpackForms(formPath):
    '''Обработка исходников после сборки обработки,
       удаление бинарников,
       переименования
    '''

    formDirName = os.path.dirname(formPath)
    moduleBsl = os.path.normpath(formDirName + '/module.bsl')
    moduleData = os.path.normpath(formDirName + '/module.data')

    os.rename(moduleData, moduleBsl)

    formDataPath = os.path.normpath(formDirName + '/form.data')
    formPrettyDataPath = os.path.normpath(formDirName + '/form.prettydata')

    newForm = Form(formDataPath)
    newForm.read()
    newForm.removeShit()
    newForm.writePretty(formPrettyDataPath)

    for file in ['FileHeader',
                 'Form.bin',
                 'form.header',
                 'module.header',
                 'form.data']:
        filePath = os.path.normpath(formDirName + '/' + file)
        if os.path.exists(filePath):
            os.remove(filePath)


def packForms(formPath, v8unpackpath):

    formDirName = os.path.dirname(formPath)

    formDataPath = os.path.normpath(formDirName + '/form.data')
    formPrettyDataPath = os.path.normpath(formDirName + '/form.prettydata')

    # Генерация файлов для unpack из исходников

    prettyForm = Form(formPrettyDataPath)
    prettyForm.read()
    prettyForm.write(formDataPath)

    # Генерация заголовков

    fileHeaderPath = os.path.normpath(formDirName + '/FileHeader')
    FileHeaderHex = binascii.unhexlify('FFFFFF7F000200000200000000000000')

    FileHeader = open(fileHeaderPath, 'wb')
    FileHeader.write(FileHeaderHex)
    FileHeader.close()

    formHeaderPath = os.path.normpath(formDirName + '/form.header')
    FormHeaderHex = binascii.unhexlify(
        '80F3B4A62C43020080F3B4A62C4302000000000066006F0072006D0000000000'
    )

    FormHeader = open(formHeaderPath, 'wb')
    FormHeader.write(FormHeaderHex)
    FormHeader.close()

    moduleHeaderPath = os.path.normpath(formDirName + '/module.header')
    moduleHeaderHex = binascii.unhexlify(
        '80F3B4A62C43020080F3B4A62C430200000000006D006F00640075006C00650000000000'
    )

    moduleHeader = open(moduleHeaderPath, 'wb')
    moduleHeader.write(moduleHeaderHex)
    moduleHeader.close()

    # Сборка бинарной формы из исходников, перед сборкой обработки

    moduleBslPath = os.path.join(formDirName, 'module.bsl')
    moduleDataPath = os.path.join(formDirName, 'module.data')
    formBinPath = os.path.join(formDirName, 'Form.bin')

    if os.path.exists(moduleDataPath):
        os.remove(moduleDataPath)

    os.rename(moduleBslPath, moduleDataPath)

    if os.path.exists(moduleBslPath):
        os.remove(moduleBslPath)

    v8unpackpath = os.path.normpath(v8unpackpath)

    сmdStr = f'""{v8unpackpath}" -PA "{formDirName}" "{formBinPath}""'

    result = os.system(сmdStr)
    if result != 0:
        raise Exception('Не удалось собрать ' + formDirName)


def build(epf, xml, v8unpack, enterpriseVersion=None, useThreadPool=False):

    # Подготовка окружения
    print('..Готовим окружение.', end="\r")

    if os.path.exists(epf):
        os.remove(epf)

    with tempfile.TemporaryDirectory() as tempdir:
        copy_tree(os.path.dirname(xml), tempdir)
        xml = os.path.join(tempdir, os.path.basename(xml))

        Enterprise = EnterpriseManager(enterpriseVersion)
        srcForms = findFiles(Enterprise.getEpfDumpRoot(xml), 'form.prettydata')

        # Собрать обычные формы в form.bin
        print('..Восстанавливаем обычные формы.', end="\r")

        if useThreadPool:
            with ThreadPool() as pool:
                pool.starmap(packForms,
                             zip(srcForms,
                                 itertools.repeat(v8unpack)
                                 )
                             )

        else:
            with Pool() as pool:
                pool.starmap(packForms, zip(
                    srcForms, itertools.repeat(v8unpack)))

        # Собрать исходники в epf
        print(f'..Создаем обработку "{epf}" из "{xml}".')

        Enterprise.epfBuid(xml, epf)

        print('..Успешно завершено')


def unpack(epf, xml, v8unpack, enterpriseVersion=None):

    print(f'..Разбираем обработку "{epf}" в "{xml}".')

    # Выгрузка обработки в XML формат

    Enterprise = EnterpriseManager(enterpriseVersion)
    Enterprise.epfDump(epf, xml)

    # Распаковка обычных форм в исходники в "Своем формата"

    binariesForms = findFiles(Enterprise.getEpfDumpRoot(xml), 'Form.bin')

    print('..Разбираем обычные формы.', end="\r")

    with Pool() as pool:
        pool.starmap(unpackForms, zip(
            binariesForms, itertools.repeat(v8unpack)))

    with Pool() as pool:
        pool.map(afterUnpackForms, binariesForms)

    print(
        f'..Успешно завершено. Обработано: {len(binariesForms)} обычных форм.')


def findFiles(path, mask, mask_ignore=".git/"):

    result = []

    for i in pathlib.Path(path).rglob(mask):
        if mask_ignore not in str(i):
            result.append(str(i))

    return result


def unpack_all(path, repo_root, v8unpack, enterpriseVersion=None):

    # Найдем все обработки

    mask = "*.epf"
    epf_list = findFiles(path, mask)

    # Разберем все обработки

    for epf in epf_list:
        xml = getXmlpathForEpf(epf, repo_root)
        unpack(epf=epf,
               xml=xml,
               v8unpack=v8unpack,
               enterpriseVersion=enterpriseVersion)


def precommit(path, v8unpack, enterpriseVersion=None):

    # Если указана директория каталога проекта, то сменим рабочую директорию
    if path is not None:
        os.chdir(path)

    # Сравним состояние репозитория с индексированными файлами
    status = GitStatus()

    # Проверим, это может быть мерж
    if status.itsmerge:
        precommit_merge(path, v8unpack, enterpriseVersion, status)

    else:
        precommit_parse(path, v8unpack, enterpriseVersion, status)

    print('..Успешно завершено.')


def precommit_parse(path, v8unpack, enterpriseVersion, status):

    # Интересует список только измененных обработок
    epf_list = [x for x in status.A + status.M if x.endswith(".epf")]

    if not epf_list:

        print('..Нет измененных/новых обработок в индексе.')
        return

    # Разбор на исходники всех обработок
    print('..Разбираем обработки на исходники.')
    for epf in epf_list:
        xml = getXmlpathForEpf(epf, path)
        unpack(
            epf=epf,
            xml=xml,
            v8unpack=v8unpack,
            enterpriseVersion=enterpriseVersion
        )

        # Индексируем новые исходники
        print('..Добавляем файлы в индекс.')
        dirPath = os.path.dirname(xml)
        git_add(dirPath)


def precommit_merge(path, v8unpack, enterpriseVersion, status):

    # Найдем все обработки в репо
    epf_in_repo_list = git_epf_in_repo(path)
    epf_build_list = []

    for new in status.A + status.M:
        for epf in epf_in_repo_list:

            srcPath = os.path.abspath(getSrcRootpathForEpf(epf, path))
            filePath = os.path.abspath(new)

            if srcPath in filePath and not epf in epf_build_list:
                epf_build_list.append(epf)

    if not epf_build_list:

        print('..В индексе нет измененных исходников обработок.')
        return

    print('..Собираем обработки из исходников после мержа.')
    for epf in epf_build_list:
        xml = getXmlpathForEpf(epf, path)
        build(
            epf=epf,
            xml=xml,
            v8unpack=v8unpack,
            enterpriseVersion=enterpriseVersion
        )

        # Индексируем новые собранные epf
        print('..Добавляем файлы в индекс.')
        git_add(epf)


def getXmlpathForEpf(epf, path):

    epf = os.path.abspath(epf)
    path = os.path.abspath(path)

    assert pathlib.Path(path) in pathlib.Path(epf).parents

    dirPath = os.path.relpath(epf, path)
    xmlPath = os.path.join(path, "src",  dirPath)
    xmlPath = os.path.normpath(xmlPath.replace(".epf", ".xml"))
    return xmlPath


def getSrcRootpathForEpf(epf, path):

    epf = os.path.abspath(epf)
    path = os.path.abspath(path)

    assert pathlib.Path(path) in pathlib.Path(epf).parents

    dirPath = os.path.relpath(epf, path)
    srcRoot = os.path.join(path, "src",  dirPath)
    srcRoot = os.path.normpath(srcRoot.replace(".epf", "/"))
    return srcRoot


def git_add(path=None):

    CmdStr = f'git add {path}'
    result = os.system(CmdStr)
    if result != 0:
        raise Exception('Не удалось проиндексировать новые файлы')

def git_epf_in_repo(path=None):

    cmd = "git ls-files --cached -- *.epf"
    returned_output = subprocess.check_output(cmd)
    out = returned_output.decode("utf-8")
    return out.splitlines()

def get_status(path=None):

    # Возвращает `git status` строку

    if not path:
        path = os.getcwd()
    cmd = "git status -s"
    returned_output = subprocess.check_output(cmd)
    out = returned_output.decode("utf-8")
    return out


class GitStatus:

    # `git status` парсер

    __readme__ = ["startswith", "A", "D", "M", "R", "untracked"]
    path = None
    out = None

    def __init__(self, path=None):
        if not path:
            path = os.getcwd()
        self.path = path
        self.out = get_status(path)

    def _startswith(self, string):
        """return list of files startswith string"""
        lines = []
        for line in self.out.splitlines():
            index = 4 - len(string)
            if line.startswith(string):
                lines.append(line.split(" ")[index])
        return lines

    def _itsmerge(self):

        cmd = "git rev-parse -q --verify MERGE_HEAD"
        result = subprocess.run(cmd, stdout=subprocess.PIPE)

        return result.returncode == 0

    @property
    def A(self):
        """return list of added files"""
        return self._startswith("A ")

    @property
    def D(self):
        """return list of deleted files"""
        return self._startswith("D ")

    @property
    def M(self):
        """return list of modified files"""
        return self._startswith("M ")

    @property
    def R(self):
        """return list of renamed files"""
        return self._startswith("R ")

    @property
    def UU(self):
        """return list of unresolved files"""
        return self._startswith("UU")

    @property
    def untracked(self):
        """return list of untracked files"""
        return self._startswith("??")

    @property
    def itsmerge(self):
        """return true or false"""
        return self._itsmerge()


def find_v8unpack(path=None):

    path_list = []
    v8unpack_file = None
    v8unpack_mask = 'v8unpack.exe'

    if path is None:
        # Если не передали путь, то попробуем найти везде,
        # но это может быть долго
        # Сначала попробуем поискать в precommit1c

        precommit1c_path = "C:/Program Files (x86)/OneScript/lib/precommit1c"
        path_list.append(precommit1c_path)
        path = os.getcwd()

    path_list.append(path)

    for path in path_list:

        print(
            f'..Ищем файл v8unpack.exe в каталоге "{path}" рекурсивно.', end="\r")
        v8unpack_list = findFiles(path, v8unpack_mask)

        if v8unpack_list:

            v8unpack_file = v8unpack_list[0]
            print(f'..Используем файл "{v8unpack_file}".')
            return v8unpack_file

    return v8unpack_file


def check_input_file(value):

    if not os.path.exists(value):
        raise argparse.ArgumentTypeError(f"не найден файл {value}")
    return value


def parse_args():

    parser = argparse.ArgumentParser(
        prog='unpackpy',
        description='Утилита для сборки/разборки/прекоммита'
        ' обработки 1С:Предприятие'
    )
    # Общие аргументы
    parser.add_argument(
        '--enterpriseVersion',
        help='Версия 1С:Предприятие'
    )

    parser.add_argument(
        '--v8unpack',
        help='Путь до утилиты V8Unpack',
        type=check_input_file
    )

    subparsers = parser.add_subparsers(
        dest="command",
        help='Команды:'
    )
    # parse
    parse_command = subparsers.add_parser(
        "parse",
        help='Разбирает указанную обработку на исходники'
    )

    parse_command.add_argument(
        "--epf",
        help="Файл с обработкой .epf",
        required=True,
        type=check_input_file
    )

    parse_command.add_argument(
        "--xml",
        help="Файл с исходниками .xml"
    )

    parse_command.set_defaults(func=parse_in)

    # parse-all

    parse_all_command = subparsers.add_parser(
        "parse-all",
        help='Разбирает все обработки в директории'
    )

    parse_all_command.add_argument(
        "--path",
        help='Путь к директории (с обработками)',
        default=".",
        type=check_input_file
    )

    parse_all_command.add_argument(
        "--repo-root",
        help='Путь к директории, в которую выгрузить исходники'
    )

    parse_all_command.set_defaults(func=parse_all_in)

    # build
    build_command = subparsers.add_parser(
        "build",
        help="Собирает обработку из исходников"
    )

    build_command.add_argument(
        "--epf",
        help="Файл с обработкой .epf",
        required=True
    )

    build_command.add_argument(
        "--xml",
        help="Файл с исходниками .xml",
        type=check_input_file,
        required=True
    )

    build_command.set_defaults(func=build_in)

    # precommit
    precommit_command = subparsers.add_parser(
        "precommit",
        help='Разбирает на исходники все измененные обработки'
        ' в индексе git репозитория,'
        ' после чего добавляет их в индекс'
    )

    precommit_command.add_argument(
        "--path",
        default=".",
        help="Путь к каталогу проекта"
    )

    precommit_command.set_defaults(func=precommit_in)

    return parser.parse_args()


def parse_in(args):

    unpack(epf=args.epf,
           xml=args.xml,
           v8unpack=args.v8unpack,
           enterpriseVersion=args.enterpriseVersion)


def parse_all_in(args):

    unpack_all(path=args.path,
               repo_root=args.repo_root,
               v8unpack=args.v8unpack,
               enterpriseVersion=args.enterpriseVersion)


def build_in(args):

    build(epf=args.epf,
          xml=args.xml,
          v8unpack=args.v8unpack,
          enterpriseVersion=args.enterpriseVersion)


def precommit_in(args):

    precommit(path=args.path,
              v8unpack=args.v8unpack,
              enterpriseVersion=args.enterpriseVersion)


def validate_args(args):

    path = None

    if hasattr(args, 'path'):
        path = args.path

    if hasattr(args, 'epf'):
        path = os.path.dirname(args.epf)

    if (args.command == "parse-all" and
            args.repo_root is None):
        args.repo_root = args.path

    if args.v8unpack is None:
        args.v8unpack = find_v8unpack(path)

    if (args.command == "parse" and
            args.xml is None):
        args.xml = getXmlpathForEpf(args.epf, path)

    if args.v8unpack is None:
        raise Exception('Не удалось найти файл v8unpack.exe,'
                        'укажите аргумент --v8unpack.')


def main():

    args = parse_args()
    validate_args(args)
    args.func(args)


if __name__ == '__main__':

    main()
