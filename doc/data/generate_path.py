from romea_path_tools.path import Path

def main():
    path = Path()
    path.name = 'test'
    path.columns = ['x', 'y', 'speed']  # 'x' and 'y' are required
    path.anchor = (45.76277, 3.110397, 403.6)  # INRAE, Aubière, France

    path.append_point([12.5, 3.2, 1.0])
    path.append_point([12.6, 3.2, 1.0])
    path.append_point([12.7, 3.3, 1.0])
    path.append_point([12.75, 3.43, 1.0])

    path.save('/tmp/test.traj')


if __name__ == '__main__':
    main()
