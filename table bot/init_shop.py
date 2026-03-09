from app import app, db
from models import ShopItem

with app.app_context():
    # Проверяем, есть ли уже товары, чтобы не дублировать
    if ShopItem.query.count() == 0:
        item1 = ShopItem(
            name="Снятие предупреждения", 
            price=800, 
            description="Позволяет аннулировать одно активное предупреждение в личном деле.",
            image_url="https://i.imgur.com/8Qp6u7C.png" # Можешь заменить на свою
        )
        
        item2 = ShopItem(
            name="Снятие выговора", 
            price=1500, 
            description="Официальный приказ о снятии дисциплинарного взыскания (выговора).",
            image_url="https://i.imgur.com/8Qp6u7C.png"
        )

        db.session.add(item1)
        db.session.add(item2)
        db.session.commit()
        print("✅ Тестовые товары успешно добавлены в базу!")
    else:
        print("⚠️ Товары уже есть в базе данных.")