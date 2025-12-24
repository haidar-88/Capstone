import Node, Edge, Platoon

platoon1 = Platoon.Platoon(1001)
car1 = Node.Node(1, 200, 200, 60, 100, 90, 1234, 5678, 5, None, True, 1)
car2 = Node.Node(2, 400, 130, 70, 150, 110, 3433, 3434, 2, None, False, 0.8)
car3 = Node.Node(3, 100, 150, 50, 60, 50, 7473, 2737, 3, None, False, 0.2)
platoon1.add_node(car1)
platoon1.add_node(car2)
platoon1.add_node(car3)
car1.platoon = platoon1
car2.platoon = platoon1
car3.platoon = platoon1

connection1_a_b = Edge.Edge(car1, car2, 10)
connection1_b_a = Edge.Edge(car2, car1, 10)
car1.add_connection(car2, connection1_a_b)
car2.add_connection(car1, connection1_b_a)

print(car1, end = '\n\n\n')
print(car2, end = '\n\n\n')
print(platoon1)