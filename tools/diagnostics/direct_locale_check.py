                      
import json

print("Прямая проверка ключей локализации:")
print("=" * 40)

langs = ['ru', 'en', 'az', 'tr']
for lang in langs:
    with open(f'locales/{lang}.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
        key_value = data.get("btn_detailed_help", "NOT FOUND")
        print(f'{lang.upper()}: btn_detailed_help = "{key_value}"')

print("\nПроверка завершена!")
