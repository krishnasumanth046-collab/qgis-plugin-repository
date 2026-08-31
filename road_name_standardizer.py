
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsProject,
    QgsSpatialIndex,
    QgsField,
    QgsRasterLayer,
    QgsRectangle
)
import os
import re
import tempfile
import pytesseract
from qgis.utils import iface

class RoadNameStandardizer:
    def __init__(self, iface):
        self.iface = iface
        self.action = None

    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        self.action = QAction(QIcon(icon_path), "Standardize Road Names", self.iface.mainWindow())
        self.action.triggered.connect(self.assign_labels_and_standardize)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("Road Name Standardizer", self.action)

    def unload(self):
        self.iface.removePluginMenu("Road Name Standardizer", self.action)
        self.iface.removeToolBarIcon(self.action)

    def assign_labels_and_standardize(self):
        road_layers = QgsProject.instance().mapLayersByName("Road Centerlines")
        label_layers = QgsProject.instance().mapLayersByName("labels")
        raster_layers = [l for l in QgsProject.instance().mapLayers().values() if isinstance(l, QgsRasterLayer)]

        if not road_layers:
            print("Error: 'Road Centerlines' layer not found.")
            return

        road_layer = road_layers[0]
        label_layer = label_layers[0] if label_layers else None
        raster_layer = raster_layers[0] if raster_layers else None

        if not road_layer.isEditable():
            if not road_layer.startEditing():
                print("Error: Cannot edit 'Road Centerlines' layer.")
                return

        field_names = [f.name() for f in road_layer.fields()]
        new_fields = []
        for name in ["road_name", "prefix", "fullname", "type"]:
            if name not in field_names:
                new_fields.append(QgsField(name, QVariant.String))

        if new_fields:
            road_layer.dataProvider().addAttributes(new_fields)
            road_layer.updateFields()

        suffix_lookup = {
            "ST": "STREET", "AVE": "AVENUE", "RD": "ROAD", "BLVD": "BOULEVARD",
            "LN": "LANE", "DR": "DRIVE", "CT": "COURT", "PL": "PLACE", "HWY": "HIGHWAY",
            "PKWY": "PARKWAY", "TER": "TERRACE", "WAY": "WAY", "TRAIL": "TRAIL",
            "EXPY": "EXPRESSWAY", "CIR": "CIRCLE", "BYP": "BYPASS", "ROW": "RIGHT OF WAY"
        }
        prefix_pattern = re.compile(r"^(N|S|E|W|NE|NW|SE|SW)\b", re.IGNORECASE)

        if label_layer:
            label_index = QgsSpatialIndex(label_layer.getFeatures())
            label_features = {f.id(): f for f in label_layer.getFeatures()}
        else:
            label_index = None
            label_features = {}

        for road_feat in road_layer.getFeatures():
            geom = road_feat.geometry()
            road_name = road_feat["road_name"]

            if not road_name and label_layer and label_index:
                nearby_ids = label_index.intersects(geom.buffer(0.0001, 5).boundingBox())
                closest_label = None
                min_dist = float("inf")
                for lid in nearby_ids:
                    label_feat = label_features[lid]
                    dist = geom.distance(label_feat.geometry())
                    if dist < min_dist and dist <= 0.0001:
                        min_dist = dist
                        closest_label = label_feat
                if closest_label:
                    road_name = closest_label["label"].strip().upper()
                    road_feat["road_name"] = road_name

            if not road_name and raster_layer:
                tmpfile = os.path.join(tempfile.gettempdir(), "ocr_tile.png")
                iface.mapCanvas().saveAsImage(tmpfile)
                try:
                    text = pytesseract.image_to_string(tmpfile)
                    if text.strip():
                        road_name = text.strip().splitlines()[0].strip().upper()
                        road_feat["road_name"] = road_name
                except Exception as e:
                    print(f"OCR failed: {e}")

            if not road_name:
                continue

            prefix_match = prefix_pattern.match(road_name)
            prefix = prefix_match.group(1).upper() if prefix_match else "N"
            name_wo_prefix = re.sub(rf"^{prefix}\s+", "", road_name, flags=re.IGNORECASE)
            suffix_abbr = name_wo_prefix.split()[-1]
            full_type = suffix_lookup.get(suffix_abbr.upper(), suffix_abbr.upper())
            name_wo_suffix = re.sub(rf"\s+{suffix_abbr}$", "", name_wo_prefix, flags=re.IGNORECASE)
            fullname = f"{name_wo_suffix} {full_type}".upper()

            road_feat["prefix"] = prefix
            road_feat["fullname"] = fullname
            road_feat["type"] = full_type

            road_layer.updateFeature(road_feat)

        road_layer.commitChanges()
        print("Standardization complete.")
