from vehicle import vehicle, platoon, edge

from AI.Smart_Decision import pick_a_charger

# Create platoon
platoon1 = platoon.Platoon(1001)

# Create 6 cars with different data
car1 = vehicle.vehicle(1, 200, 200, 60, 100, 90, 1234, 5678, 5, None, True, 1)
car2 = vehicle.vehicle(2, 400, 130, 70, 150, 110, 3433, 3434, 2, None, False, 0.8)
car3 = vehicle.vehicle(3, 100, 150, 50, 60, 50, 7473, 2737, 3, None, False, 0.2)
car4 = vehicle.vehicle(4, 350, 300, 80, 120, 130, 8888, 9999, 4, None, False, 0.6)
car5 = vehicle.vehicle(5, 500, 250, 65, 180, 75, 1111, 2222, 1, None, False, 0.9)
car6 = vehicle.vehicle(6, 150, 400, 55, 90, 110, 3333, 4444, 3, None, False, 0.7)

# Add all cars to platoon
cars = [car1, car2, car3, car4, car5, car6]
for car in cars:
    platoon1.add_vehicle(car)
    car.platoon = platoon1

# Create edges with different costs
# Car1 connections
connection1_2 = edge.Edge(car1, car2, 15)
connection2_1 = edge.Edge(car2, car1, 12)
connection1_3 = edge.Edge(car1, car3, 8)
connection3_1 = edge.Edge(car3, car1, 10)

# Car2 connections
connection2_4 = edge.Edge(car2, car4, 20)
connection4_2 = edge.Edge(car4, car2, 18)
connection2_5 = edge.Edge(car2, car5, 25)
connection5_2 = edge.Edge(car5, car2, 22)

# Car3 connections
connection3_6 = edge.Edge(car3, car6, 30)
connection6_3 = edge.Edge(car6, car3, 28)

# Car4 connections
connection4_5 = edge.Edge(car4, car5, 7)
connection5_4 = edge.Edge(car5, car4, 7)

# Car5 connections
connection5_6 = edge.Edge(car5, car6, 14)
connection6_5 = edge.Edge(car6, car5, 14)

# Car6 connections
connection6_1 = edge.Edge(car6, car1, 35)
connection1_6 = edge.Edge(car1, car6, 32)

# Add all connections to cars
# Car1
car1.add_connection(car2, connection1_2)
car1.add_connection(car3, connection1_3)
car1.add_connection(car6, connection1_6)

# Car2
car2.add_connection(car1, connection2_1)
car2.add_connection(car4, connection2_4)
car2.add_connection(car5, connection2_5)

# Car3
car3.add_connection(car1, connection3_1)
car3.add_connection(car6, connection3_6)

# Car4
car4.add_connection(car2, connection4_2)
car4.add_connection(car5, connection4_5)

# Car5
car5.add_connection(car2, connection5_2)
car5.add_connection(car4, connection5_4)
car5.add_connection(car6, connection5_6)

# Car6
car6.add_connection(car3, connection6_3)
car6.add_connection(car5, connection6_5)
car6.add_connection(car1, connection6_1)

# Print all cars
for i, car in enumerate(cars, 1):
    print(f"=== Car {i} ===")
    print(car)
    print()

print(end="\n\n")

# Print platoon summary
print("=== Platoon Summary ===")
print(platoon1)

print("--------------------------------------", end="\n\n")
#choosen_charger = pick_a_charger(car2, platoon1, 100)
#print(choosen_charger)