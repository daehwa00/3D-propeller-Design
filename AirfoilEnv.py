import numpy as np
from xfoil import XFoil
from xfoil.model import Airfoil
from scipy.spatial import ConvexHull
import matplotlib.pyplot as plt
import os
import sys
from contextlib import contextmanager

class CustomAirfoilEnv:
    """
    x는 0 ~ 0.8, r은 0 ~ 0.2
        circles = [
        ((0, 0), 0.05),
        ((0.1, 0), 0.10),
        ((0.3, 0), 0.15),
        ((0.4, 0), 0.14),
        ((1, 0), 0.001),
    ]
    """

    def __init__(self, env_batch_size=1):
        self.xfoil = XFoil()
        self.xfoil.Re = 1e6
        self.xfoil.max_iter = 100  # 최대 반복 횟수
        self.circles = [((0, 0), 0.05), ((1, 0), 0.001)]
        self.state = self.get_airfoil_points(self.circles)
        self.xfoil.airfoil = Airfoil(self.state[:, 0], self.state[:, 1])
        self.states = np.zeros((env_batch_size, 32))
        # 초기 상태 설정 등

        self.env_batch_size = env_batch_size

    def reset(self):
        self.circles = [((0, 0), 0.05), ((1, 0), 0.001)]
        self.state = self.get_airfoil_points(self.circles)
        self.xfoil.airfoil = Airfoil(self.state[:, 0], self.state[:, 1])
        return self.get_state()

    def step(self, action):
        action = action.squeeze()
        # 입력으로 0 ~ 1 사이를 받기 때문에 scaling 해야함
        action[0] = action[0] * 0.8
        action[1] = action[1] * 0.2

        self.circles.append(((action[0], 0), action[1]))  # add circle
        new_airfoil_points = self.get_airfoil_points(self.circles)
        self.xfoil.airfoil = Airfoil(new_airfoil_points[:, 0], new_airfoil_points[:, 1])
        cl, cd, cm, cp = self.xfoil.a(5)

        reward = cl / cd

        if reward == 0:
            reward = -1

        # 다음 상태를 결정합니다. 실제 프로젝트에서는 변경된 에어포일 형상 등을 상태로 사용할 수 있습니다.
        next_state = self.get_state()
        self.state = next_state

        return next_state, reward

    def get_state(self):
        return self.state

    def generate_all_circle_points(self, circles, num_points=100):
        """
        여러 원들에 대한 점들을 생성하고 합칩니다.

        :param circles: 각 원의 (중심, 반지름) 튜플을 포함하는 리스트입니다.
        :param num_points: 각 원을 대표하는 점의 수입니다 (기본값: 100).
        :return: 생성된 모든 원들의 점들을 합친 numpy 배열입니다.
        """

        def generate_circle_points(center, radius, num_points=100):
            return np.array(
                [
                    [
                        center[0] + np.cos(2 * np.pi / num_points * x) * radius,
                        center[1] + np.sin(2 * np.pi / num_points * x) * radius,
                    ]
                    for x in range(num_points)
                ]
            )

        # 모든 원들의 점들을 생성하고 합칩니다.
        all_points = np.concatenate(
            [
                generate_circle_points(center, radius, num_points)
                for center, radius in circles
            ]
        )

        return all_points

    def interpolate_linear_functions(self, hull_points, N=100):
        x_min = np.min(hull_points[:, 0])
        x_argmin = np.argmin(hull_points[:, 0])
        y_standard = hull_points[x_argmin, 1]
        hull_points -= [x_min, y_standard]

        N_front = int(0.3 * N)
        N_back = N - N_front

        # x 좌표의 최대값으로 모든 x 좌표를 정규화
        x_max = np.max(hull_points[:, 0])
        hull_points[:, 0] /= x_max
        hull_points[:, 1] /= x_max  # y 좌표도 x 최대값으로 나누어 비율 유지

        hull_points = np.vstack([hull_points, hull_points[0]])  # 경로 닫기

        # x 좌표를 기준으로 정렬 (시계 방향 또는 반시계 방향 보장)
        hull_points = hull_points[np.argsort(hull_points[:, 0])]

        # UPPER
        upper_hull_points = hull_points[hull_points[:, 1] >= 0]
        # 각 선분에 대한 x 및 y의 기울기 계산
        upper_dx = np.diff(upper_hull_points[:, 0])
        upper_dy = np.diff(upper_hull_points[:, 1])
        upper_slopes = upper_dy / upper_dx
        upper_intercepts = (
            upper_hull_points[:-1, 1] - upper_slopes * upper_hull_points[:-1, 0]
        )

        # N+1을 사용하고 endpoint=False를 추가합니다.
        upper_front_x_values = np.geomspace(
            0.0001, 0.1, N_front, endpoint=False
        )  # 0 대신 최소값으로 시작
        upper_back_x_values = np.linspace(0.1, 1, N_back, endpoint=True)
        upper_x_values = np.concatenate((upper_front_x_values, upper_back_x_values))
        upper_y_values = np.zeros(N)

        upper_current_segment = 0
        for i in range(N):
            upper_x = upper_x_values[i]
            while (
                upper_current_segment < len(upper_slopes) - 1
                and upper_x > upper_hull_points[upper_current_segment + 1, 0]
            ):
                upper_current_segment += 1
            upper_y_values[i] = (
                upper_slopes[upper_current_segment] * upper_x
                + upper_intercepts[upper_current_segment]
            )

        upper_x_values = np.flip(upper_x_values)  # x 좌표를 다시 뒤집습니다.
        upper_y_values = np.flip(upper_y_values)
        # LOWER
        lower_hull_points = hull_points[hull_points[:, 1] <= 0]

        lower_dx = np.diff(lower_hull_points[:, 0])
        lower_dy = np.diff(lower_hull_points[:, 1])
        lower_slopes = lower_dy / lower_dx
        lower_intercepts = (
            lower_hull_points[:-1, 1] - lower_slopes * lower_hull_points[:-1, 0]
        )

        lower_front_x_values = np.geomspace(
            0.0001, 0.1, N_front, endpoint=False
        )  # 0 대신 최소값으로 시작
        lower_back_x_values = np.linspace(0.1, 1, N_back, endpoint=True)
        lower_x_values = np.concatenate((lower_front_x_values, lower_back_x_values))
        lower_y_values = np.zeros(N)

        lower_current_segment = 0
        for i in range(N):
            lower_x = lower_x_values[i]
            while (
                lower_current_segment < len(lower_slopes) - 1
                and lower_x > lower_hull_points[lower_current_segment + 1, 0]
            ):
                lower_current_segment += 1
            lower_y_values[i] = (
                lower_slopes[lower_current_segment] * lower_x
                + lower_intercepts[lower_current_segment]
            )

        x_values = np.concatenate((upper_x_values, lower_x_values))
        y_values = np.concatenate((upper_y_values, lower_y_values))
        values = np.vstack((x_values, y_values)).T

        return values

    def get_airfoil_points(self, circles, N=100, plot=False):
        all_points = self.generate_all_circle_points(circles)
        hull = ConvexHull(all_points)
        hull_points = all_points[hull.vertices]
        interpolated_points = self.interpolate_linear_functions(hull_points, N=N)
        if plot:
            # plt.figure(figsize=(10, 5))
            # xlim과 ylim을 같게 설정하여 비율을 유지합니다.
            plt.gca().set_aspect("equal")
            plt.plot(
                np.array(hull_points[:, 0]),
                np.array(hull_points[:, 1]),
                "o-",
                label="Hull Points",
            )
            plt.plot(
                np.array(interpolated_points[:, 0]),
                np.array(interpolated_points[:, 1]),
                ".r",
                label="Interpolated Points",
            )
            plt.legend()
            plt.xlabel("X")
            plt.ylabel("Y")
            plt.title("Linear Interpolation of Convex Hull Points")
            plt.show()
        else:
            # plt.figure(figsize=(10, 5))
            # xlim과 ylim을 같게 설정하여 비율을 유지합니다.
            plt.gca().set_aspect("equal")
            plt.plot(
                np.array(hull_points[:, 0]),
                np.array(hull_points[:, 1]),
                "o-",
                label="Hull Points",
            )
            plt.plot(
                np.array(interpolated_points[:, 0]),
                np.array(interpolated_points[:, 1]),
                ".r",
                label="Interpolated Points",
            )
            plt.legend()
            plt.xlabel("X")
            plt.ylabel("Y")
            plt.title("Linear Interpolation of Convex Hull Points")
            plt.savefig('airfoil.png')
        return interpolated_points