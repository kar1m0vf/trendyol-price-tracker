#!/usr/bin/env python3
"""
Демо-скрипт для демонстрации системы управления рекомендуемыми продуктами
"""
import sys
sys.path.insert(0, '.')

from database import add_recommended_product, get_recommended_products, remove_recommended_product
from bot import get_available_products

def demo():
    print("🎯 Демо системы управления рекомендуемыми продуктами")
    print("=" * 60)

    # Очищаем старые тестовые данные
    print("\n🧹 Очищаем старые тестовые данные...")
    products = get_recommended_products()
    for product in products:
        if "Test" in product['title'] or "Demo" in product['title']:
            remove_recommended_product(product['id'])
            print(f"  Удален: {product['title']}")

    # Добавляем демо-продукты
    print("\n➕ Добавляем демо-продукты...")

    demo_products = [
        {
            "title": "iPhone 15 Pro Max",
            "url": "https://www.trendyol.com/apple/iphone-15-pro-max-p-123456",
            "price": "₺52,000",
            "category": "smartphones",
            "brand": "apple",
            "reason_template": "Новейший флагман Apple с топовой камерой",
            "priority": 10
        },
        {
            "title": "Samsung Galaxy S24 Ultra",
            "url": "https://www.trendyol.com/samsung/galaxy-s24-ultra-p-789012",
            "price": "₺48,000",
            "category": "smartphones",
            "brand": "samsung",
            "reason_template": "Мощный конкурент с S-Pen",
            "priority": 8
        },
        {
            "title": "Nike Air Max 270",
            "url": "https://www.trendyol.com/nike/air-max-270-p-345678",
            "price": "₺3,200",
            "category": "shoes",
            "brand": "nike",
            "reason_template": "Комфортные кроссовки для повседневного использования",
            "priority": 5
        },
        {
            "title": "MacBook Air M3",
            "url": "https://www.trendyol.com/apple/macbook-air-m3-p-901234",
            "price": "₺38,000",
            "category": "laptops",
            "brand": "apple",
            "reason_template": "Легкий и мощный ноутбук для работы",
            "priority": 9
        }
    ]

    added_ids = []
    for product in demo_products:
        success = add_recommended_product(
            title=product["title"],
            url=product["url"],
            price=product["price"],
            category=product["category"],
            brand=product["brand"],
            reason_template=product["reason_template"],
            priority=product["priority"]
        )
        if success:
            print(f"  ✅ Добавлен: {product['title']} (приоритет: {product['priority']})")
            # Получаем ID только что добавленного продукта
            products = get_recommended_products()
            for p in products:
                if p['title'] == product['title']:
                    added_ids.append(p['id'])
                    break
        else:
            print(f"  ❌ Ошибка при добавлении: {product['title']}")

    # Показываем все рекомендуемые продукты
    print("\n📋 Все рекомендуемые продукты:")
    products = get_recommended_products()
    for product in products:
        print(f"  🆔 {product['id']}: {product['title']}")
        print(f"     💰 {product['price']} | 🎯 {product['category']} | ⭐ {product['priority']}")
        print(f"     🔗 {product['url']}")
        print()

    # Тестируем функцию get_available_products
    print("🔍 Тестируем get_available_products():")
    available = get_available_products()
    print(f"  Найдено {len(available)} доступных продуктов")
    print("  Продукты отсортированы по приоритету:")
    for i, product in enumerate(available[:3], 1):
        priority = product.get('priority', 0)
        print(f"    {i}. {product['title']} (приоритет: {priority})")

    # Примеры команд для админа
    print("\n📚 Примеры команд для администратора:")
    print("  /admin recommend list                    # Показать все продукты")
    print("  /admin recommend add \"Sony WH-1000XM5\" \"https://trendyol.com/sony/wh1000-p-999\" \"₺8,500\" headphones sony \"Топовые наушники с шумоподавлением\"")
    print("  /admin recommend remove 2                # Удалить продукт с ID 2")
    print("  /admin recommend priority 3 15           # Изменить приоритет продукта 3 на 15")

    print("\n✅ Демо завершено! Система готова к использованию.")
    print("=" * 60)

if __name__ == "__main__":
    demo()
