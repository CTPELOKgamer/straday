import os
import json
import zipfile
import struct
import base64
from typing import Dict, Any, Optional, List
import io


class CPMModelConverter:
    """
    Конвертер для файлов Custom Player Models
    Конвертирует .cpmmodel в .cpmproject на основе реального анализа формата
    """
    
    def __init__(self):
        self.debug = False
    
    def set_debug(self, debug: bool):
        """Включить/выключить отладочный вывод"""
        self.debug = debug
    
    def _debug_print(self, message: str):
        """Вывод отладочной информации"""
        if self.debug:
            print(f"[DEBUG] {message}")
    
    def _read_string(self, data: bytes, offset: int) -> tuple[str, int]:
        """
        Читает строку из бинарных данных
        Возвращает (строка, новый_offset)
        """
        # Читаем длину строки (4 байта, little-endian)
        if offset + 4 > len(data):
            return "", offset
        
        str_len = struct.unpack('<I', data[offset:offset+4])[0]
        offset += 4
        
        if offset + str_len > len(data):
            return "", offset
        
        # Читаем строку в UTF-8
        try:
            string = data[offset:offset+str_len].decode('utf-8')
        except UnicodeDecodeError:
            string = data[offset:offset+str_len].decode('utf-8', errors='ignore')
        
        offset += str_len
        return string, offset
    
    def _read_texture_data(self, data: bytes, offset: int) -> tuple[bytes, int]:
        """
        Читает данные текстуры из бинарных данных
        Возвращает (данные_текстуры, новый_offset)
        """
        if offset + 4 > len(data):
            return b"", offset
        
        tex_size = struct.unpack('<I', data[offset:offset+4])[0]
        offset += 4
        
        if tex_size == 0 or offset + tex_size > len(data):
            return b"", offset
        
        tex_data = data[offset:offset+tex_size]
        offset += tex_size
        
        return tex_data, offset
    
    def read_cpmmodel(self, file_path: str) -> Dict[str, Any]:
        """
        Читает .cpmmodel файл и извлекает данные
        Основан на анализе реального файла формата
        """
        try:
            with open(file_path, 'rb') as f:
                data = f.read()
            
            self._debug_print(f"Размер файла: {len(data)} байт")
            
            model_data = {
                'textures': [],
                'model': {},
                'animations': {},
                'metadata': {}
            }
            
            offset = 0
            
            # Ищем JSON данные в файле (они обычно начинаются с '{')
            json_start = -1
            for i in range(len(data) - 1):
                if data[i] == ord('{'):
                    # Проверяем, что это начало JSON
                    try:
                        # Ищем конец JSON
                        brace_count = 1
                        json_end = i + 1
                        while json_end < len(data) and brace_count > 0:
                            if data[json_end] == ord('{'):
                                brace_count += 1
                            elif data[json_end] == ord('}'):
                                brace_count -= 1
                            json_end += 1
                        
                        if brace_count == 0:
                            json_data = data[i:json_end].decode('utf-8')
                            model_json = json.loads(json_data)
                            model_data['model'] = model_json
                            json_start = i
                            self._debug_print(f"Найден JSON на позиции {i}, размер: {json_end - i}")
                            break
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
            
            # Извлекаем текстуры
            # Ищем PNG заголовки в файле
            png_signature = b'\x89PNG\r\n\x1a\n'
            tex_count = 0
            
            search_start = 0
            while True:
                png_pos = data.find(png_signature, search_start)
                if png_pos == -1:
                    break
                
                # Ищем конец PNG файла
                png_end = data.find(b'IEND', png_pos)
                if png_end != -1:
                    png_end += 8  # IEND + CRC
                    png_data = data[png_pos:png_end]
                    
                    model_data['textures'].append({
                        'name': f'texture_{tex_count}.png',
                        'data': png_data
                    })
                    
                    self._debug_print(f"Найдена текстура {tex_count}, размер: {len(png_data)} байт")
                    tex_count += 1
                
                search_start = png_pos + 1
            
            # Если JSON не найден, создаем базовую структуру
            if not model_data['model']:
                self._debug_print("JSON не найден, создаем базовую структуру")
                model_data['model'] = {
                    "version": 1,
                    "parts": [],
                    "animations": {},
                    "poses": {},
                    "scaling": {}
                }
            
            # Извлекаем метаданные из имени файла
            filename = os.path.basename(file_path)
            model_name = os.path.splitext(filename)[0]
            
            model_data['metadata'] = {
                'filename': filename,
                'model_name': model_name,
                'file_size': len(data)
            }
            
            self._debug_print(f"Обработка завершена: модель={len(model_data['model'])}, текстур={len(model_data['textures'])}")
            
            return model_data
            
        except Exception as e:
            self._debug_print(f"Ошибка при чтении файла: {e}")
            return {}
    
    def create_cpmproject(self, model_data: Dict[str, Any], output_path: str):
        """
        Создает .cpmproject файл из данных модели
        """
        try:
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Создаем project.json
                metadata = model_data.get('metadata', {})
                project_info = {
                    "version": "0.6.0",
                    "name": metadata.get('model_name', 'Converted Model'),
                    "description": f"Converted from {metadata.get('filename', '.cpmmodel')}",
                    "author": "CPM Converter",
                    "exportVersion": "1.0.0"
                }
                
                zipf.writestr('project.json', json.dumps(project_info, indent=2, ensure_ascii=False))
                self._debug_print("Создан project.json")
                
                # Добавляем model.json
                model_json = model_data.get('model', {})
                
                # Если модель пустая, создаем базовую структуру
                if not model_json or not model_json.get('parts'):
                    model_json = {
                        "version": 11,
                        "parts": [],
                        "scaling": {
                            "head": [1.0, 1.0, 1.0],
                            "body": [1.0, 1.0, 1.0],
                            "leftArm": [1.0, 1.0, 1.0],
                            "rightArm": [1.0, 1.0, 1.0],
                            "leftLeg": [1.0, 1.0, 1.0],
                            "rightLeg": [1.0, 1.0, 1.0]
                        },
                        "animations": {},
                        "poses": {},
                        "root": []
                    }
                
                zipf.writestr('model.json', json.dumps(model_json, indent=2, ensure_ascii=False))
                self._debug_print("Создан model.json")
                
                # Добавляем текстуры
                textures_added = 0
                for i, texture in enumerate(model_data.get('textures', [])):
                    tex_name = texture.get('name', f'texture_{i}.png')
                    tex_data = texture.get('data', b'')
                    
                    if tex_data:
                        # Убеждаемся, что путь начинается с textures/
                        if not tex_name.startswith('textures/'):
                            tex_path = f'textures/{tex_name}'
                        else:
                            tex_path = tex_name
                        
                        zipf.writestr(tex_path, tex_data)
                        textures_added += 1
                        self._debug_print(f"Добавлена текстура: {tex_path}")
                
                # Создаем базовые папки
                if textures_added == 0:
                    zipf.writestr('textures/.keep', '')
                
                zipf.writestr('animations/.keep', '')
                
                self._debug_print(f"Создан .cpmproject с {textures_added} текстурами")
                
        except Exception as e:
            print(f"Ошибка при создании .cpmproject файла: {e}")
            raise
    
    def convert_cpmmodel_to_cpmproject(self, input_path: str, output_path: str = None) -> bool:
        """
        Основная функция конвертации .cpmmodel в .cpmproject
        """
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Файл {input_path} не найден")
        
        if not input_path.lower().endswith('.cpmmodel'):
            raise ValueError("Входной файл должен иметь расширение .cpmmodel")
        
        if output_path is None:
            output_path = input_path.rsplit('.', 1)[0] + '.cpmproject'
        
        print(f"Конвертирование: {input_path} -> {output_path}")
        
        try:
            # Читаем данные из .cpmmodel
            model_data = self.read_cpmmodel(input_path)
            
            if not model_data:
                print("❌ Не удалось прочитать данные из .cpmmodel файла")
                return False
            
            # Создаем .cpmproject
            self.create_cpmproject(model_data, output_path)
            
            print(f"✅ Конвертация завершена успешно!")
            print(f"   Создан файл: {output_path}")
            print(f"   Текстур извлечено: {len(model_data.get('textures', []))}")
            
            return True
            
        except Exception as e:
            print(f"❌ Ошибка при конвертации: {e}")
            return False
    
    def batch_convert(self, input_directory: str, output_directory: str = None) -> Dict[str, int]:
        """
        Пакетная конвертация всех .cpmmodel файлов в директории
        """
        if not os.path.exists(input_directory):
            raise FileNotFoundError(f"Директория {input_directory} не найдена")
        
        if output_directory is None:
            output_directory = input_directory
        
        if not os.path.exists(output_directory):
            os.makedirs(output_directory)
        
        results = {'success': 0, 'failed': 0, 'total': 0}
        failed_files = []
        
        # Ищем все .cpmmodel файлы
        cpmmodel_files = []
        for filename in os.listdir(input_directory):
            if filename.lower().endswith('.cpmmodel'):
                cpmmodel_files.append(filename)
        
        results['total'] = len(cpmmodel_files)
        
        if results['total'] == 0:
            print("❌ Не найдено .cpmmodel файлов в указанной директории")
            return results
        
        print(f"🔄 Найдено {results['total']} .cpmmodel файлов для конвертации")
        print("-" * 50)
        
        for filename in cpmmodel_files:
            input_path = os.path.join(input_directory, filename)
            output_filename = filename.rsplit('.', 1)[0] + '.cpmproject'
            output_path = os.path.join(output_directory, output_filename)
            
            print(f"Обрабатывается: {filename}")
            
            try:
                if self.convert_cpmmodel_to_cpmproject(input_path, output_path):
                    results['success'] += 1
                else:
                    results['failed'] += 1
                    failed_files.append(filename)
            except Exception as e:
                print(f"❌ Ошибка при обработке {filename}: {e}")
                results['failed'] += 1
                failed_files.append(filename)
            
            print("-" * 30)
        
        # Итоговый отчет
        print("\n" + "="*50)
        print("📊 ИТОГОВЫЙ ОТЧЕТ")
        print("="*50)
        print(f"Всего файлов: {results['total']}")
        print(f"✅ Успешно: {results['success']}")
        print(f"❌ Ошибок: {results['failed']}")
        
        if failed_files:
            print(f"\nНе удалось конвертировать:")
            for file in failed_files:
                print(f"  - {file}")
        
        return results
    
    def analyze_cpmmodel(self, file_path: str):
        """
        Анализирует структуру .cpmmodel файла для отладки
        """
        print(f"🔍 Анализ файла: {file_path}")
        print("="*50)
        
        try:
            with open(file_path, 'rb') as f:
                data = f.read()
            
            print(f"Размер файла: {len(data)} байт")
            
            # Показываем первые 100 байт в hex
            print(f"\nПервые 100 байт (hex):")
            hex_data = data[:100].hex()
            for i in range(0, len(hex_data), 32):
                print(f"{i//2:04x}: {hex_data[i:i+32]}")
            
            # Ищем JSON
            json_positions = []
            for i in range(len(data) - 1):
                if data[i] == ord('{'):
                    json_positions.append(i)
            
            print(f"\nНайдено потенциальных JSON блоков: {len(json_positions)}")
            for pos in json_positions[:5]:  # Показываем первые 5
                print(f"  Позиция: {pos} (0x{pos:x})")
            
            # Ищем PNG файлы
            png_signature = b'\x89PNG\r\n\x1a\n'
            png_positions = []
            search_start = 0
            while True:
                pos = data.find(png_signature, search_start)
                if pos == -1:
                    break
                png_positions.append(pos)
                search_start = pos + 1
            
            print(f"\nНайдено PNG файлов: {len(png_positions)}")
            for i, pos in enumerate(png_positions):
                print(f"  PNG {i+1}: позиция {pos} (0x{pos:x})")
            
            # Анализируем строки
            strings = []
            i = 0
            while i < len(data) - 4:
                if data[i:i+4] == b'\x00\x00\x00\x00':
                    i += 4
                    continue
                
                # Пытаемся прочитать как длину строки
                try:
                    str_len = struct.unpack('<I', data[i:i+4])[0]
                    if 0 < str_len < 1000 and i + 4 + str_len < len(data):
                        try:
                            string = data[i+4:i+4+str_len].decode('utf-8')
                            if string.isprintable() and len(string) > 2:
                                strings.append((i, string))
                        except UnicodeDecodeError:
                            pass
                except struct.error:
                    pass
                i += 1
            
            print(f"\nНайдено читаемых строк: {len(strings)}")
            for pos, string in strings[:10]:  # Показываем первые 10
                print(f"  {pos:04x}: '{string[:50]}'")
            
        except Exception as e:
            print(f"❌ Ошибка при анализе: {e}")


def main():
    """
    Интерактивный интерфейс конвертера
    """
    converter = CPMModelConverter()
    
    print("🎮 CPM Model Converter")
    print("Конвертер .cpmmodel в .cpmproject для Custom Player Models")
    print("="*60)
    
    while True:
        print("\nВыберите действие:")
        print("1. Конвертировать один файл")
        print("2. Пакетная конвертация")
        print("3. Анализ .cpmmodel файла")
        print("4. Включить/выключить отладку")
        print("0. Выход")
        
        choice = input("\nВаш выбор (0-4): ").strip()
        
        if choice == '0':
            print("👋 До свидания!")
            break
        
        elif choice == '1':
            input_file = input("Путь к .cpmmodel файлу: ").strip().strip('"')
            
            if not input_file:
                print("❌ Путь не указан")
                continue
            
            output_file = input("Путь для .cpmproject файла (Enter для автоматического): ").strip().strip('"')
            if not output_file:
                output_file = None
            
            try:
                converter.convert_cpmmodel_to_cpmproject(input_file, output_file)
            except Exception as e:
                print(f"❌ Ошибка: {e}")
        
        elif choice == '2':
            input_dir = input("Директория с .cpmmodel файлами: ").strip().strip('"')
            
            if not input_dir:
                print("❌ Путь не указан")
                continue
            
            output_dir = input("Директория для .cpmproject файлов (Enter для той же): ").strip().strip('"')
            if not output_dir:
                output_dir = None
            
            try:
                converter.batch_convert(input_dir, output_dir)
            except Exception as e:
                print(f"❌ Ошибка: {e}")
        
        elif choice == '3':
            input_file = input("Путь к .cpmmodel файлу для анализа: ").strip().strip('"')
            
            if not input_file:
                print("❌ Путь не указан")
                continue
            
            try:
                converter.analyze_cpmmodel(input_file)
            except Exception as e:
                print(f"❌ Ошибка: {e}")
        
        elif choice == '4':
            current_debug = converter.debug
            converter.set_debug(not current_debug)
            status = "включена" if converter.debug else "выключена"
            print(f"🔧 Отладка {status}")
        
        else:
            print("❌ Неверный выбор")


if __name__ == "__main__":
    main()
