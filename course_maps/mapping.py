import copy
import yaml
import os
import json
import folium
import haversine as hs
import pandas as pd
import numpy as np
import math
import string
from geographiclib.geodesic import Geodesic


def coord_to_latlon(string):
    if not isinstance(string, str):
        lat, lon = [np.nan] * 2
    else:
        lat, lat_min, lon, lon_min = [float(x) for x in string.split(' ')]
        lat += np.sign(lat) * (lat_min / 60)
        lon += np.sign(lon) * (lon_min / 60)

    return pd.Series([lat, lon])

def latlon_to_coord(ll_list):
    pass


def coord_mean(coord_df):
    if not all(coord_df.dtypes == [float, float]):
        coord_df = coord_df.apply(coord_to_latlon)
    return tuple(coord_df.sum() / len(coord_df.dropna()))


def coord_diff(coord_df, units=hs.Unit.METERS):
    # Distance from center point
    center = coord_mean(coord_df)

    if not all(coord_df.dtypes == [float, float]):
        coord_df = coord_df.apply(coord_to_latlon)

    return coord_df.apply(lambda x: hs.haversine(center, tuple(x), unit=units), axis=1).max()


def get_bearing(point_list):
    lat1, long1, lat2, long2 = [x for point in point_list for x in point]
    bearing = Geodesic.WGS84.Inverse(lat1, long1, lat2, long2)['azi1']
    compass_bearing = (bearing + 360) % 360
    return compass_bearing


def get_bearing_man(point_list):
    lat1, long1, lat2, long2 = [x for point in point_list for x in point]
    dLon = (long2 - long1)
    x = math.cos(math.radians(lat2)) * math.sin(math.radians(dLon))
    y = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(math.radians(dLon))
    bearing = np.arctan2(x, y)
    bearing = np.degrees(bearing)
    compass_bearing = (bearing + 360) % 360
    return compass_bearing

class CourseCharting:
    def __init__(self, **kwargs):
        # Set default kwargs
        defaultKwargs = {'static': True,
                         'pin': 'T1',
                         'rounding': 'PORT',
                         'custom_coords': {},
                         'is_mobile': False}
        kwargs = {**defaultKwargs, **kwargs}

        # Setup class vars
        for k, v in kwargs.items():
            setattr(self, k, v)

        self.marks = self.objects = self.order = None
        # self.course_number = course_number
        self.settings = {'data_dir': 'course_maps/fixtures/map_data',
                         'course_data': {
                             'marks': 'course_marks.csv',
                             'objects': 'course_objects.yaml',
                             'order': 'course_order.yaml'}
                         }
        if self.static:
            self.load_static_data()

    def plot_course(self):

        #TODO map doesn't scale, need to get pixels somehow...
        if self.is_mobile:
            height = '100%'

        # Map overall center point
        center = coord_mean(self.marks[['lat', 'lon']])
        # Plot map and marks
        m = folium.Map(location=center, zoom_start=13, height='100%', width='100%')

        segment_points = []
        course_df = copy.deepcopy(self.order[str(self.course_number)])

        for index, course_object in self.order[str(self.course_number)].iterrows():

            # if len(self.objects[course_object.name]['points']) > 1:
            if course_object.rounding is not None and course_object.rounding.upper() == 'GATE':
                object_marks = self.objects[course_object.name]['points']
                object_coords = self.marks.loc[object_marks]

                # If START, select which pin
                if course_object.name == 'START':
                    object_coords = object_coords.loc[['RC BOAT', self.pin]]
                    # Update any custom coordinates
                    for cc in self.custom_coords:
                        object_coords.loc[cc, ['lat', 'lon']] = self.custom_coords[cc]

                # Get effective center from remaining points (if there were more than 2)
                object_center = coord_mean(object_coords[['lat', 'lon']])

                # Effective mark location (center)
                mark = course_object
                mark['precision_value'] = 40  # coord_diff(object_coords, units=hs.Unit.METERS)

                mark['latlon'] = object_center
                for k, v in iter(zip(['lat', 'lon'], object_center)):
                    mark[k] = v

                # Plot gate segment
                for name, gate_point in object_coords.iterrows():
                    folium.Circle(
                        radius=gate_point.precision_value,
                        location=(gate_point.lat, gate_point.lon),
                        popup=name,
                        color="blue",
                        fill=False,
                    ).add_to(m)

                gate_points = object_coords[['lat', 'lon']].to_numpy().tolist()
                folium.PolyLine(gate_points, color="blue", weight=2.5, opacity=1).add_to(m)

            else:
                # If starboard rounding, swap W and R
                if course_object.name in ['W', 'R'] and self.rounding.upper() == 'STARBOARD':
                    windward = {'W': 'R', 'R': 'W'}[course_object.name]
                    mark = copy.deepcopy(self.marks.loc[windward])
                    mark.name = course_object.name
                else:
                    mark = copy.deepcopy(self.marks.loc[course_object.name])

            # Add the rounding to the chart table
            if course_object.name in ['W', 'R']:
                course_df.loc[mark.name, 'rounding'] = self.rounding
            else:
                course_df.loc[mark.name, 'rounding'] = course_object.rounding

            mark_coords = mark[['lat', 'lon']].to_list()
            folium.Circle(
                radius=int(mark.precision_value),
                location=mark_coords,
                popup=mark.name,
                color="crimson",
                fill=False,
            ).add_to(m)

            # Waypoint segments
            segment_points.append(mark_coords)
            course_df.loc[mark.name, ['lat', 'lon']] = mark_coords

            if len(segment_points) > 1:
                # Calculate the segment bearing angle
                course_df.loc[mark.name, 'bearing'] = get_bearing(segment_points)
                folium.PolyLine(segment_points,
                                color="red", weight=2.5, opacity=1,
                                # popup=course_object.order-1
                                ).add_to(m)
                segment_points.pop(0)

        # Update map center
        m.location = coord_mean(pd.DataFrame(segment_points, columns=['lat', 'lon']))
        course_df.bearing = course_df.bearing.round().astype('Int64')
        course_df = course_df[['order', 'name', 'rounding', 'bearing', 'lat', 'lon']]
        course_df.columns = [s.capitalize() for s in course_df.columns]

        # m.save('templates/test_map.html')
        return {'chart': m, 'chart_table': course_df, 'course_number': self.course_number}

    def load_static_data(self):
        for key, file in self.settings['course_data'].items():
            fpath = os.path.join(self.settings['data_dir'], file)

            if '.csv' in file:
                data = pd.read_csv(fpath)

            with open(fpath) as f:
                if '.yaml' in file:
                    data = yaml.load(f, Loader=yaml.FullLoader)
                if '.json' in file:
                    data = json.load(f)

            # Data formatting
            if key == 'marks' and isinstance(data, pd.DataFrame):
                data[['lat', 'lon']] = data.coord_string.apply(coord_to_latlon)
                data.index = data['name']

            if key == 'objects':
                data = {x.pop('name'): x for x in data}

            if key == 'order':
                data = {str(x.pop('course_number')): pd.DataFrame(x['marks']) for x in data}
                for k, v in data.items():
                    v.index = v['name']

            setattr(self, key, data)


if __name__ == "__main__":
    # if os.path.basename(os.getcwd()) != 'course_maps':
    #     os.chdir('course_maps')
    os.chdir('../')
    print(os.getcwd())
    self = CourseCharting(**{'course_number': 6})
    self.plot_course()
