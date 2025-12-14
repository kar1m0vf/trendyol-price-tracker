"""
Тест локализации - проверка наличия всех ключей во всех языках
"""
import json
import os
from pathlib import Path

print("=" * 60)
print("ТЕСТИРОВАНИЕ ЛОКАЛИЗАЦИИ")
print("=" * 60)

locales_dir = Path("locales")
languages = ["ru", "en", "az", "tr"]

# Загружаем все локали
locales = {}
for lang in languages:
    locale_file = locales_dir / f"{lang}.json"
    if not locale_file.exists():
        print(f"❌ Файл локализации не найден: {locale_file}")
        continue
    try:
        with open(locale_file, "r", encoding="utf-8") as f:
            locales[lang] = json.load(f)
        print(f"✅ Загружена локализация: {lang} ({len(locales[lang])} ключей)")
    except Exception as e:
        print(f"❌ Ошибка загрузки {lang}: {e}")

if not locales:
    print("❌ Не удалось загрузить ни одну локализацию!")
    exit(1)

# Собираем все ключи из всех локалей
all_keys = set()
for lang, keys in locales.items():
    all_keys.update(keys.keys())

print(f"\nВсего уникальных ключей: {len(all_keys)}")

# Проверяем наличие всех ключей во всех языках
missing_keys = {}
for lang in languages:
    if lang not in locales:
        continue
    lang_keys = set(locales[lang].keys())
    missing = all_keys - lang_keys
    if missing:
        missing_keys[lang] = missing

if missing_keys:
    print("\n❌ НАЙДЕНЫ ОТСУТСТВУЮЩИЕ КЛЮЧИ:")
    for lang, keys in missing_keys.items():
        print(f"\n  {lang.upper()}: {len(keys)} отсутствующих ключей")
        for key in sorted(keys)[:10]:  # Показываем первые 10
            print(f"    - {key}")
        if len(keys) > 10:
            print(f"    ... и еще {len(keys) - 10}")
else:
    print("\n✅ Все ключи присутствуют во всех языках!")

# Проверяем пустые значения
print("\n[Проверка пустых значений]")
empty_values = {}
for lang in languages:
    if lang not in locales:
        continue
    empty = [k for k, v in locales[lang].items() if not v or v.strip() == ""]
    if empty:
        empty_values[lang] = empty

if empty_values:
    print("⚠️  Найдены пустые значения:")
    for lang, keys in empty_values.items():
        print(f"  {lang.upper()}: {len(keys)} пустых ключей")
        for key in keys[:5]:
            print(f"    - {key}")
else:
    print("✅ Пустых значений не найдено")

# Проверяем форматирование (наличие {placeholders})
print("\n[Проверка форматирования]")
format_issues = []
for lang in languages:
    if lang not in locales:
        continue
    for key, value in locales[lang].items():
        if isinstance(value, str):
            # Проверяем несоответствие фигурных скобок
            open_braces = value.count("{")
            close_braces = value.count("}")
            if open_braces != close_braces:
                format_issues.append((lang, key, f"Несоответствие скобок: {{={open_braces}, }}={close_braces}"))

if format_issues:
    print("⚠️  Найдены проблемы с форматированием:")
    for lang, key, issue in format_issues[:10]:
        print(f"  {lang}.{key}: {issue}")
else:
    print("✅ Проблем с форматированием не найдено")

print("\n" + "=" * 60)
if missing_keys or empty_values or format_issues:
    print("⚠️  Тест локализации завершен с предупреждениями")
else:
    print("✅ ТЕСТ ЛОКАЛИЗАЦИИ ПРОЙДЕН УСПЕШНО!")
print("=" * 60)

