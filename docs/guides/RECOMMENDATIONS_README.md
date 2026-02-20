# 🎯 Система управления рекомендуемыми продуктами

## Обзор

Система позволяет администратору управлять списком рекомендуемых продуктов, которые показываются пользователям в разделе "Рекомендации". Это отличная возможность для монетизации - размещения платной рекламы продуктов.

## 🚀 Быстрый старт

1. **Запустите демо:**
   ```bash
   python demo_recommendations.py
   ```

2. **Проверьте в боте:**
   - Отправьте `/admin recommend list`
   - Нажмите кнопку "🎯 Рекомендации"

## 📋 Админ команды

### Просмотр всех продуктов
```
/admin recommend list
```

### Добавление продукта
```
/admin recommend add "Название товара" "https://ссылка" "₺Цена" категория бренд "Описание"
```

**Примеры:**
```bash
/admin recommend add "iPhone 15 Pro" "https://trendyol.com/iphone-p-123" "₺45,000" smartphones apple "Новинка Apple"

/admin recommend add "Nike Air Max" "https://trendyol.com/nike-p-456" "₺2,500" shoes nike "Комфортные кроссовки"
```

### Удаление продукта
```
/admin recommend remove ID_продукта
```

**Пример:**
```bash
/admin recommend remove 5
```

### Изменение приоритета
```
/admin recommend priority ID_продукта новый_приоритет
```

**Пример:**
```bash
/admin recommend priority 3 15
```

## 📊 Как это работает

1. **Приоритетное отображение** - продукты с высоким приоритетом показываются первыми
2. **Персонализация** - система учитывает предпочтения пользователя (бренды, категории)
3. **Fallback** - если в базе нет рекомендуемых продуктов, показываются стандартные

## 🎨 Категории продуктов

- `smartphones` - смартфоны
- `laptops` - ноутбуки
- `shoes` - обувь
- `home_appliances` - бытовая техника
- `other` - другие

## 💰 Монетизация

- **Продажа рекламы** - предлагайте компаниям размещение их товаров в рекомендациях
- **Приоритетное размещение** - чем выше приоритет, тем чаще товар показывается
- **Статистика** - отслеживайте эффективность рекламы

## 🔧 Технические детали

### База данных
```sql
CREATE TABLE recommended_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    price TEXT,
    category TEXT,
    brand TEXT,
    reason_template TEXT,
    priority INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    updated_at INTEGER DEFAULT (strftime('%s', 'now'))
);
```

### API функции
- `add_recommended_product()` - добавить продукт
- `get_recommended_products()` - получить все продукты
- `remove_recommended_product()` - удалить продукт
- `update_recommended_product_priority()` - изменить приоритет

## 🎯 Примеры использования

### 1. Добавление премиум рекламы
```
/admin recommend add "Rolex Submariner" "https://trendyol.com/rolex-p-999" "₺150,000" accessories rolex "Легендарные часы премиум класса" 20
```

### 2. Сезонная реклама
```
/admin recommend add "Зимняя куртка Columbia" "https://trendyol.com/columbia-p-888" "₺2,500" clothing columbia "Теплая зимняя куртка" 15
```

### 3. Управление рекламой
```
/admin recommend list                    # Посмотреть все
/admin recommend priority 10 25         # Повысить приоритет
/admin recommend remove 5               # Убрать неэффективную рекламу
```

## ✅ Готово к использованию!

Система полностью готова к коммерческому использованию. Начните с демо-данных и постепенно добавляйте платную рекламу! 🚀

