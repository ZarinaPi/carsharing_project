from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from sqlalchemy.orm import joinedload, selectinload

app = Flask(__name__)
CORS(app)  # Разрешить запросы из браузера

# Настройка базы данных (SQLite)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# МОДЕЛИ

class CarClass(db.Model):
    """Метакласс для иерархии классификатора (таблица car_classes)"""
    __tablename__ = 'car_classes'
    
    id_class = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    short_name = db.Column(db.String(50))
    base_ei = db.Column(db.Integer, db.ForeignKey('ei.id_ei'))  # Ссылка на таблицу ei
    main_class = db.Column(db.Integer, db.ForeignKey('car_classes.id_class'))  # Рефлексивная связь
    
    # Рефлексивная связь (родитель → потомки)
    parent = db.relationship('CarClass', 
                             backref=db.backref('children', lazy='select'),
                             remote_side=[id_class])
    
    def to_dict(self):
        return {
            'id_class': self.id_class,
            'name': self.name,
            'short_name': self.short_name,
            'base_ei': self.base_ei,
            'main_class': self.main_class
        }
    
    def check_cycle(self, new_parent_id):
        """Проверка на циклы при смене родителя"""
        if new_parent_id == self.id_class:
            return True
        current = CarClass.query.get(new_parent_id)
        while current:
            if current.id_class == self.id_class:
                return True
            current = current.parent
        return False
    
    def get_all_children(self):
        """Рекурсивно найти всех потомков"""
        result = list(self.children)
        for child in self.children:
            result.extend(child.get_all_children())
        return result
    
    def get_all_parents(self):
        """Найти всех предков"""
        result = []
        current = self.parent
        while current:
            result.append(current)
            current = current.parent
        return result


class Car(db.Model):
    "Конкретные автомобили (таблица cars)"
    __tablename__ = 'cars'
    
    id_car = db.Column(db.Integer, primary_key=True)
    short_name = db.Column(db.String(20), unique=True, nullable=False)
    id_class = db.Column(db.Integer, db.ForeignKey('car_classes.id_class'), nullable=False)
    
    car_class = db.relationship('CarClass', backref='cars')
    
    def to_dict(self):
        attrs = {a.enum.name: a.value_obj.value for a in self.attributes}
        
        return {
            'id_car': self.id_car,
            'short_name': self.short_name,
            'name': self.car_class.name,
            'id_class': self.id_class,
            'attributes': attrs
        }


class Unit(db.Model):
    """Единицы измерения (таблица ei)"""
    __tablename__ = 'ei'
    id_ei = db.Column(db.Integer, primary_key=True)
    short_name = db.Column(db.String(10), nullable=False, unique=True)
    name = db.Column(db.String(50), nullable=False)
    
    def to_dict(self):
        return {
            'id_ei': self.id_ei,
            'short_name': self.short_name,
            'name': self.name
        }

# МОДЕЛИ ПЕРЕЧИСЛЕНИЙ

class Enumeration(db.Model):
    "Справочник-перечисление (CHEM_CLASS)"
    __tablename__ = 'enumerations'
    id_enum = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    value_type = db.Column(db.String(20), default='string') # string, numeric, icon
    
    # Связи
    values = db.relationship('EnumValue', backref='enumeration', lazy='select', cascade='all, delete-orphan')
    linked_classes = db.relationship('ClassEnum', backref='enumeration', lazy='select')

    def to_dict(self):
        return {
            'id_enum': self.id_enum,
            'name': self.name,
            'description': self.description,
            'value_type': self.value_type
        }

class EnumValue(db.Model):
    "Значение перечисления (POS_ENUM)"
    __tablename__ = 'enum_values'
    id_value = db.Column(db.Integer, primary_key=True)
    id_enum = db.Column(db.Integer, db.ForeignKey('enumerations.id_enum'), nullable=False)
    value = db.Column(db.String(100), nullable=False)
    sort_order = db.Column(db.Integer, default=0) # NUM из PDF
    numeric_value = db.Column(db.Float)
    icon_url = db.Column(db.String(255))
    unit_id = db.Column(db.Integer, db.ForeignKey('ei.id_ei'))
    
    unit = db.relationship('Unit')
    
    def to_dict(self):
        return {
            'id_value': self.id_value,
            'value': self.value,
            'sort_order': self.sort_order,
            'numeric_value': self.numeric_value,
            'icon_url': self.icon_url,
            'unit': self.unit.to_dict() if self.unit else None
        }

class ClassEnum(db.Model):
    "Привязка перечисления к классу автомобилей"
    __tablename__ = 'class_enums'
    id_class = db.Column(db.Integer, db.ForeignKey('car_classes.id_class'), primary_key=True)
    id_enum = db.Column(db.Integer, db.ForeignKey('enumerations.id_enum'), primary_key=True)
    is_required = db.Column(db.Boolean, default=False)
    
    car_class = db.relationship('CarClass', backref=db.backref('linked_enums', lazy='select'))

class CarEnumValue(db.Model):
    "Выбранное значение характеристики у конкретной машины"
    __tablename__ = 'car_enum_values'
    id_car = db.Column(db.Integer, db.ForeignKey('cars.id_car'), primary_key=True)
    id_enum = db.Column(db.Integer, db.ForeignKey('enumerations.id_enum'), primary_key=True)
    id_value = db.Column(db.Integer, db.ForeignKey('enum_values.id_value'), nullable=False)
    
    car = db.relationship('Car', backref=db.backref('attributes', lazy='select'))
    enum = db.relationship('Enumeration')
    value_obj = db.relationship('EnumValue')
    
    def to_dict(self):
        return {
            'id_enum': self.id_enum,
            'enum_name': self.enum.name,
            'id_value': self.id_value,
            'value': self.value_obj.value,
            'sort_order': self.value_obj.sort_order
        }

# API ЭНДПОИНТЫ (Методы сервера)

@app.route('/api/class/add', methods=['POST'])
def add_class():
    """Добавить новый класс (вершину)"""
    data = request.json
    main_class = data.get('main_class')
    
    # Проверка на цикл (если указан родитель)
    if main_class:
        # Временная проверка (упрощенная)
        pass 
    
    new_class = CarClass(
        name=data['name'],
        short_name=data.get('short_name', ''),
        base_ei=data.get('base_ei'),
        main_class=main_class
    )
    db.session.add(new_class)
    db.session.commit()
    return jsonify({'status': 'created', 'id_class': new_class.id_class}), 201


@app.route('/api/class/<int:id_class>', methods=['DELETE'])
def delete_class(id_class):
    clazz = CarClass.query.options(joinedload(CarClass.children), joinedload(CarClass.parent)).get(id_class)
    if not clazz:
        return jsonify({'error': 'Class not found'}), 404

    new_parent_id = clazz.main_class
    cars_in_class = Car.query.filter_by(id_class=id_class).all()

    # Если у класса нет родителя
    if new_parent_id is None:
        if len(cars_in_class) > 0 or clazz.children.count() > 0:
            return jsonify({
                'error': 'Cannot delete root class that contains children or cars.'
            }), 400
        
        db.session.delete(clazz)
        db.session.commit()
        return jsonify({'status': 'deleted'}), 200

    # Переносим детей
    children = CarClass.query.filter_by(main_class=id_class).all()
    for child in children:
        child.main_class = new_parent_id

    # Переносим машины
    for car in cars_in_class:
        car.id_class = new_parent_id
        
    # Фиксируем изменения перед удалением
    db.session.flush()

    # Удаляем класс
    db.session.delete(clazz)
    
    try:
        db.session.commit()
        return jsonify({
            'status': 'deleted',
            'message': f'Class deleted. {len(children)} children and {len(cars_in_class)} cars moved to parent ID {new_parent_id}.'
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/class/<int:id_class>/move', methods=['PUT'])
def move_class(id_class):
    "Переместить класс (сменить родителя)"
    data = request.json
    new_parent_id = data.get('new_parent_id')
    
    clazz = CarClass.query.options(joinedload(CarClass.parent)).get(id_class)
    if not clazz:
        return jsonify({'error': 'Class not found'}), 404
    
    # Проверка на циклы
    if clazz.check_cycle(new_parent_id):
        return jsonify({'error': 'Cycle detected!'}), 400
    
    clazz.main_class = new_parent_id
    db.session.commit()
    return jsonify({'status': 'moved'}), 200


@app.route('/api/class/<int:id_class>/children', methods=['GET'])
def get_children(id_class):
    "Найти всех потомков класса"
    clazz = CarClass.query.options(joinedload(CarClass.parent)).get(id_class)
    if not clazz:
        return jsonify({'error': 'Class not found'}), 404
    
    all_children = clazz.get_all_children()
    return jsonify({
        'class': clazz.to_dict(),
        'children': [c.to_dict() for c in all_children]
    }), 200


@app.route('/api/class/<int:id_class>/parents', methods=['GET'])
def get_parents(id_class):
    "Найти всех родителей (предков) класса"
    clazz = CarClass.query.options(joinedload(CarClass.parent)).get(id_class)
    if not clazz:
        return jsonify({'error': 'Class not found'}), 404
    
    all_parents = clazz.get_all_parents()
    return jsonify({
        'class': clazz.to_dict(),
        'parents': [p.to_dict() for p in all_parents]
    }), 200


@app.route('/api/class/terminal', methods=['GET'])
def get_terminal_classes():
    "Найти все терминальные классы (листья дерева)"
    all_classes = CarClass.query.options(selectinload(CarClass.children)).all()
    terminal = [c for c in all_classes if not c.children]
    return jsonify({'terminal_classes': [c.to_dict() for c in terminal]}), 200


@app.route('/api/class/tree', methods=['GET'])
def get_tree():
    "Просмотреть всю структуру классификатора"
    roots = CarClass.query.filter_by(main_class=None).options(selectinload(CarClass.children)).all()
    
    def build_tree(node):
        return {
            'id_class': node.id_class,
            'name': node.name,
            'children': [build_tree(child) for child in node.children]
        }
    
    return jsonify({'tree': [build_tree(r) for r in roots]}), 200


@app.route('/api/car/add', methods=['POST'])
def add_car():
    data = request.json
    
    if not data or 'short_name' not in data or 'id_class' not in data:
        return jsonify({'error': 'Fields short_name and id_class are required'}), 400
    
    # Проверка существования класса
    if not CarClass.query.get(data['id_class']):
        return jsonify({'error': 'Class not found'}), 404

    new_car = Car(
        short_name=data['short_name'],
        id_class=data['id_class']
    )
    
    try:
        db.session.add(new_car)
        db.session.commit()
        return jsonify({'status': 'created', 'id_car': new_car.id_car}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/car/<int:id_car>', methods=['DELETE'])
def delete_car(id_car):
    "Удалить конкретный автомобиль"
    car = Car.query.get(id_car)
    if not car:
        return jsonify({'error': 'Car not found'}), 404
    
    db.session.delete(car)
    db.session.commit()
    return jsonify({'status': 'deleted'}), 200

@app.route('/api/car/<int:id_car>', methods=['PUT'])
def update_car(id_car):
    car = Car.query.get(id_car)
    if not car:
        return jsonify({'error': 'Car not found'}), 404
    
    data = request.json
    
    if 'id_class' in data: 
        target_class = CarClass.query.get(data['id_class'])
        if not target_class:
            return jsonify({'error': 'Target class does not exist'}), 404
        car.id_class = data['id_class']
    
    try:
        db.session.commit()
        return jsonify({'status': 'updated', 'car': car.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/cars', methods=['GET'])
def get_cars():
    "Получить список всех автомобилей"
    cars = Car.query.options(joinedload(Car.car_class)).all()
    return jsonify({'cars': [c.to_dict() for c in cars]}), 200


@app.route('/api/cars/<int:id_class>', methods=['GET'])
def get_cars_by_class(id_class):
    "Получить автомобили по классу (включая потомков)"
    clazz = CarClass.query.get(id_class)
    if not clazz:
        return jsonify({'error': 'Class not found'}), 404
    
    # Получить все потомков (включая сам класс)
    all_classes = [clazz] + clazz.get_all_children()
    class_ids = [c.id_class for c in all_classes]
    
    cars = Car.query.filter(Car.id_class.in_(class_ids)).options(joinedload(Car.car_class)).all()
    return jsonify({'cars': [c.to_dict() for c in cars]}), 200


# API ДЛЯ ПЕРЕЧИСЛЕНИЙ

#1. Управление самими перечислениями (справочниками)

@app.route('/api/enumeration/add', methods=['POST'])
def add_enumeration():
    """Создать новое перечисление (справочник)"""
    data = request.json
    
    if not data or 'name' not in data:
        return jsonify({'error': 'Field "name" is required'}), 400
    
    new_enum = Enumeration(
        name=data['name'],
        description=data.get('description', ''),
        value_type=data.get('value_type', 'string')  # 'string', 'numeric', 'icon'
    )
    
    try:
        db.session.add(new_enum)
        db.session.commit()
        return jsonify({'status': 'created', 'id_enum': new_enum.id_enum}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/enumerations', methods=['GET'])
def get_enumerations():
    """Получить список всех перечислений"""
    enums = Enumeration.query.all()
    return jsonify({'enumerations': [e.to_dict() for e in enums]}), 200

@app.route('/api/enumeration/<int:id_enum>', methods=['GET'])
def get_enumeration(id_enum):
    """Получить перечисление со всеми значениями"""
    enum = Enumeration.query.get(id_enum)
    if not enum:
        return jsonify({'error': 'Enumeration not found'}), 404
    
    # Получаем все значения, отсортированные по sort_order
    values = EnumValue.query.filter_by(id_enum=id_enum)\
                           .order_by(EnumValue.sort_order)\
                           .all()
    
    result = enum.to_dict()
    result['values'] = [v.to_dict() for v in values]
    return jsonify(result), 200

@app.route('/api/enumeration/<int:id_enum>', methods=['PUT'])
def update_enumeration(id_enum):
    """Редактировать перечисление"""
    enum = Enumeration.query.get(id_enum)
    if not enum:
        return jsonify({'error': 'Enumeration not found'}), 404
    
    data = request.json
    
    if 'name' in data:
        enum.name = data['name']
    if 'description' in data:
        enum.description = data['description']
    if 'value_type' in data:
        enum.value_type = data['value_type']
    
    try:
        db.session.commit()
        return jsonify({'status': 'updated', 'enumeration': enum.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/enumeration/<int:id_enum>', methods=['DELETE'])
def delete_enumeration(id_enum):
    "Удалить перечисление (вместе со значениями)"
    enum = Enumeration.query.get(id_enum)
    if not enum:
        return jsonify({'error': 'Enumeration not found'}), 404
    
    try:
        db.session.delete(enum)
        db.session.commit()
        return jsonify({'status': 'deleted'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

#Управление значениями перечислений

@app.route('/api/enumeration/<int:id_enum>/value/add', methods=['POST'])
def add_enum_value(id_enum):
    "Добавить значение в перечисление"
    enum = Enumeration.query.get(id_enum)
    if not enum:
        return jsonify({'error': 'Enumeration not found'}), 404
    
    data = request.json
    
    if not data or 'value' not in data:
        return jsonify({'error': 'Field "value" is required'}), 400
    
    new_value = EnumValue(
        id_enum=id_enum,
        value=data['value'],
        sort_order=data.get('sort_order', 0),
        numeric_value=data.get('numeric_value'),
        icon_url=data.get('icon_url'),
        unit_id=data.get('unit_id')  # Ссылка на единицу измерения
    )
    
    try:
        db.session.add(new_value)
        db.session.commit()
        return jsonify({'status': 'created', 'id_value': new_value.id_value}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/enumeration/<int:id_enum>/values', methods=['GET'])
def get_enum_values(id_enum):
    "Получить все значения перечисления (отсортированные)"
    enum = Enumeration.query.get(id_enum)
    if not enum:
        return jsonify({'error': 'Enumeration not found'}), 404
    
    values = EnumValue.query.filter_by(id_enum=id_enum)\
                           .order_by(EnumValue.sort_order)\
                           .all()
    
    return jsonify({'values': [v.to_dict() for v in values]}), 200

@app.route('/api/enum-value/<int:id_value>', methods=['PUT'])
def update_enum_value(id_value):
    value = EnumValue.query.get(id_value)
    if not value:
        return jsonify({'error': 'Value not found'}), 404

    data = request.json

    if 'sort_order' in data:
        new_order = data['sort_order']
        id_enum = value.id_enum

        # Сдвигаем все значения этого справочника, которые >= нового порядка
        EnumValue.query.filter(
            EnumValue.id_enum == id_enum,
            EnumValue.sort_order >= new_order,
            EnumValue.id_value != id_value
        ).update({EnumValue.sort_order: EnumValue.sort_order + 1}, synchronize_session=False)

        value.sort_order = new_order
    else:
        # Обновляем остальные поля без сдвига
        if 'value' in data:
            value.value = data['value']
        if 'numeric_value' in data:
            value.numeric_value = data['numeric_value']
        if 'icon_url' in data:
            value.icon_url = data['icon_url']
        if 'unit_id' in data:
            value.unit_id = data['unit_id']

    try:
        db.session.commit()
        return jsonify({'status': 'updated', 'value': value.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/enum-value/<int:id_value>', methods=['DELETE'])
def delete_enum_value(id_value):
    """Удалить значение из перечисления"""
    value = EnumValue.query.get(id_value)
    if not value:
        return jsonify({'error': 'Value not found'}), 404
    
    try:
        db.session.delete(value)
        db.session.commit()
        return jsonify({'status': 'deleted'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/class/<int:id_class>/enum/link', methods=['POST'])
def link_enum_to_class(id_class):
    "Привязать справочник к классу автомобилей"
    clazz = CarClass.query.get(id_class)
    if not clazz:
        return jsonify({'error': 'Class not found'}), 404

    data = request.json
    enumeration = Enumeration.query.get(data.get('id_enum'))
    if not enumeration:
        return jsonify({'error': 'Enumeration not found'}), 404

    # Проверка на дубликаты (нельзя привязать один справочник дважды)
    existing_link = ClassEnum.query.get((id_class, enumeration.id_enum))
    if existing_link:
        return jsonify({'error': 'Enumeration is already linked to this class'}), 409

    # Создаем связь
    # is_required - обязательно ли заполнять это поле (флаг из PDF)
    link = ClassEnum(
        id_class=id_class,
        id_enum=enumeration.id_enum,
        is_required=data.get('is_required', False)
    )
    db.session.add(link)
    db.session.commit()
    return jsonify({'status': 'linked', 'is_required': link.is_required}), 201

@app.route('/api/class/<int:id_class>/enums', methods=['GET'])
def get_class_enums(id_class):
    """Получить все доступные справочники для данного класса + наследование от родителей"""
    clazz = CarClass.query.get(id_class)
    if not clazz:
        return jsonify({'error': 'Class not found'}), 404

    # Собираем ВСЕ справочники: от самого класса + от всех родителей
    all_enums = {}  # Словарь для избежания дубликатов (ключ=id_enum)
    
    # Рекурсивная функция для сбора справочников по иерархии
    def collect_enums_from_class(cls):
        # 1. Добавляем справочники текущего класса
        for link in cls.linked_enums:
            if link.enumeration.id_enum not in all_enums:
                all_enums[link.enumeration.id_enum] = {
                    'enum': link.enumeration,
                    'is_required': link.is_required
                }
        
        # 2. Если есть родительский класс (main_class), идём вверх по иерархии
        if cls.main_class:
            parent = CarClass.query.get(cls.main_class)
            if parent:
                collect_enums_from_class(parent)
    
    # Запускаем сбор с текущего класса
    collect_enums_from_class(clazz)
    
    # 3. Формируем итоговый ответ
    result = []
    for enum_data in all_enums.values():
        enum = enum_data['enum']
        enum_dict = enum.to_dict()
        enum_dict['is_required'] = enum_data['is_required']
        
        # Получаем значения, отсортированные по sort_order
        values = EnumValue.query.filter_by(id_enum=enum.id_enum)\
                               .order_by(EnumValue.sort_order)\
                               .all()
        
        enum_dict['values'] = [v.to_dict() for v in values]
        result.append(enum_dict)
    
    return jsonify({'enums': result}), 200

@app.route('/api/car/<int:id_car>/attribute', methods=['PUT'])
def set_car_attribute(id_car):
    """Установить/изменить характеристику у конкретной машины (с учетом наследования)"""
    car = Car.query.get(id_car)
    if not car:
        return jsonify({'error': 'Car not found'}), 404

    data = request.json
    id_enum = data.get('id_enum')
    id_value = data.get('id_value')

    # Проверяем, привязан ли этот справочник к классу машины ИЛИ к любому из её родителей
    def is_enum_allowed_for_class(cls_id, enum_id):
        # Проверяем прямую привязку
        link = ClassEnum.query.get((cls_id, enum_id))
        if link:
            return True
        
        # Если нет, проверяем родителя (рекурсивно)
        clazz = CarClass.query.get(cls_id)
        if clazz and clazz.main_class:
            return is_enum_allowed_for_class(clazz.main_class, enum_id)
        
        return False

    if not is_enum_allowed_for_class(car.id_class, id_enum):
        return jsonify({'error': f'Enumeration {id_enum} is not allowed for this class'}), 400

    # Проверяем, существует ли такое значение в этом справочнике
    val = EnumValue.query.get(id_value)
    if not val or val.id_enum != id_enum:
        return jsonify({'error': f'Value {id_value} does not belong to enumeration {id_enum}'}), 400

    # Сохраняем или обновляем
    attribute = CarEnumValue.query.get((id_car, id_enum))
    
    if attribute:
        attribute.id_value = id_value
    else:
        attribute = CarEnumValue(id_car=id_car, id_enum=id_enum, id_value=id_value)
        db.session.add(attribute)

    try:
        db.session.commit()
        return jsonify({'status': 'updated', 'attribute': attribute.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/car/<int:id_car>/attributes', methods=['GET'])
def get_car_attributes(id_car):
    """Получить все характеристики машины"""
    car = Car.query.get(id_car)
    if not car:
        return jsonify({'error': 'Car not found'}), 404

    attributes = CarEnumValue.query.filter_by(id_car=id_car).all()
    return jsonify({'attributes': [a.to_dict() for a in attributes]}), 200


# API ДЛЯ ЕДИНИЦ ИЗМЕРЕНИЯ (таблица ei)

@app.route('/api/units', methods=['GET'])
def get_units():
    """Получить все единицы измерения"""
    units = Unit.query.all()
    return jsonify({'units': [u.to_dict() for u in units]}), 200

@app.route('/api/unit/<int:id_ei>', methods=['GET'])
def get_unit(id_ei):
    """Получить единицу измерения по ID"""
    unit = Unit.query.get(id_ei)
    if not unit:
        return jsonify({'error': 'Unit not found'}), 404
    return jsonify(unit.to_dict()), 200

@app.route('/api/unit/add', methods=['POST'])
def add_unit():
    """Создать новую единицу измерения"""
    data = request.json
    
    if not data or 'short_name' not in data or 'name' not in data:
        return jsonify({'error': 'Fields short_name and name are required'}), 400
    
    # Проверка на дубликат сокращённого названия
    if Unit.query.filter_by(short_name=data['short_name']).first():
        return jsonify({'error': 'Unit with this short_name already exists'}), 409
        
    new_unit = Unit(short_name=data['short_name'], name=data['name'])
    try:
        db.session.add(new_unit)
        db.session.commit()
        return jsonify({'status': 'created', 'id_ei': new_unit.id_ei}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/unit/<int:id_ei>', methods=['PUT'])
def update_unit(id_ei):
    "Редактировать единицу измерения"
    unit = Unit.query.get(id_ei)
    if not unit:
        return jsonify({'error': 'Unit not found'}), 404
    
    data = request.json
    
    if 'short_name' in data:
        # Проверяем уникальность при изменении
        existing = Unit.query.filter(Unit.short_name == data['short_name'], Unit.id_ei != id_ei).first()
        if existing:
            return jsonify({'error': 'Short name already exists'}), 409
        unit.short_name = data['short_name']
        
    if 'name' in data:
        unit.name = data['name']
        
    try:
        db.session.commit()
        return jsonify({'status': 'updated', 'unit': unit.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/unit/<int:id_ei>', methods=['DELETE'])
def delete_unit(id_ei):
    "Удалить единицу измерения"
    unit = Unit.query.get(id_ei)
    if not unit:
        return jsonify({'error': 'Unit not found'}), 404
    
    try:
        db.session.delete(unit)
        db.session.commit()
        return jsonify({'status': 'deleted'}), 200
    except Exception as e:
        db.session.rollback()
        # Если на эту единицу ссылаются enum_values, SQLite вернёт ошибку FK
        return jsonify({'error': str(e)}), 500


# ЗАПУСК СЕРВЕРА

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Создать таблицы БД
        
        # Добавить корневой класс и единицу измерения, если нет
        if not Unit.query.first():
            db.session.add(Unit(short_name='шт', name='штуки'))
            db.session.commit()
        
        if not CarClass.query.first():
            root = CarClass(name='Каталог Каршеринга', short_name='ROOT')
            db.session.add(root)
            db.session.commit()
            print('База данных создана и заполнена тестовыми данными!')
    
    print('Сервер запущен на http://127.0.0.1:5000')
    app.run(debug=False, port=5000)