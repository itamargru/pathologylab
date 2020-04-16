from mrcnn import utils
import os
import sys
import json
import datetime
import numpy as np
import skimage.draw
import cv2


############################################################
#  Dataset
############################################################

class PDL1NetDataset(utils.Dataset):

    def load_pdl1net_dataset(self, dataset_dir, subset):
        """Load a subset of the PDL1 dataset.
        dataset_dir: Root directory of the dataset.
        subset: Subset to load: train or val
        """
        # Add classes. We have only one class to add.
        self.add_class("PDL1", 1, "inflammation")
        self.add_class("PDL1", 2, "negative")
        self.add_class("PDL1", 3, "positive")
        # if we decide to delete the next line reduce the number of classes in the config
        self.add_class("PDL1", 4, "other")

        ids = [c["id"] for c in self.class_info]
        names = [c["name"] for c in self.class_info]
        self.class_name2id = dict(zip(names, ids))

        # Train or validation dataset?
        # TODO: change the path to the right one
        # assert subset in ["train", "val"]
        dataset_dir = os.path.join(dataset_dir, subset)

        # Load annotations
        # VGG Image Annotator saves each image in the form:
        # { 'filename': '28503151_5b5b7ec140_b.jpg',
        #   'regions': {
        #       '0': {
        #           'region_attributes': {},
        #           'shape_attributes': {
        #               'all_points_x': [...],
        #               'all_points_y': [...],
        #               'name': 'polygon'}},
        #       ... more regions ...
        #   },
        #   'size': 100202
        # }
        # We mostly care about the x and y coordinates of each region
        # TODO: make sure the json has the right name
        # ATTENTION! the parser will work only for via POLYGON segmented regions
        # annotations = json.load(open(os.path.join(dataset_dir, "train_synth_via_json.json")))
        annotations = json.load(open(os.path.join(dataset_dir, "via_export_json.json")))
        annotations = list(annotations.values())  # don't need the dict keys

        # The VIA tool saves images in the JSON even if they don't have any
        # annotations. Skip unannotated images.
        annotations = [a for a in annotations if a['regions']]
        # type2class = {"1":"inflammation", "2":"negative", "3":"positive", "4":"other"}
        type2class = {"inf": "inflammation", "neg": "negative", "pos": "positive", "other": "other"}
        # Add images
        for a in annotations:
            # Get the x, y coordinaets of points of the polygons that make up
            # the outline of each object instance. There are stores in the
            # shape_attributes (see json format above)
            polygons = [r['shape_attributes'] for r in a['regions']]
            classes = [r['region_attributes']['category'] for r in a['regions']]  # validate that a list of classes is obtained
            classes = [type2class[c] for c in classes]

            # load_mask() needs the image size to convert polygons to masks.
            # Unfortunately, VIA doesn't include it in JSON, so we must read
            # the image. This is only managable since the dataset is tiny.
            image_path = os.path.join(dataset_dir, a['filename'])
            image = skimage.io.imread(image_path)
            height, width = image.shape[:2]

            self.add_image(
                "PDL1",
                image_id=a['filename'],  # use file name as a unique image id
                path=image_path,
                width=width, height=height,
                polygons=polygons,
                classes=classes)

    def load_mask(self, image_id):
        """Generate instance masks for an image.
       Returns:
        masks: A bool array of shape [height, width, instance count] with
            one mask per instance.
        class_ids: a 1D array of class IDs of the instance masks.
        """
        # If not a PDL1 dataset image, delegate to parent class.
        info = self.image_info[image_id]
        if info["source"] != "PDL1":
            return super(self.__class__, self).load_mask(image_id)

        # Convert polygons to a bitmap mask of shape
        # [height, width, instance_count]
        mask = np.zeros([info["height"], info["width"], len(info["polygons"])],
                        dtype=np.uint8)
        # TODO: make sure no intersection are made between polygons
        for i, p in enumerate(info["polygons"]):
            # Get indexes of pixels inside the polygon and set them to 1
            if p['all_points_y'] is None or p['all_points_x'] is None:
                continue
            #  check if an element in the list is also a list
            if any(isinstance(elem, list) for elem in p['all_points_y']) or any(isinstance(elem, list) for elem in p['all_points_x']):
                continue
            rr, cc = skimage.draw.polygon(p['all_points_y'], p['all_points_x'])
            mask[rr, cc, i] = 1
        # mask_classes = [self.class_name2id[name] for name in self.class_names]
        mask_classes = [self.class_name2id[name] for name in info["classes"]]
        mask_classes = np.array(mask_classes, dtype=np.int32)

        # clean masks intersections
        # create united mask for each class
        united_masks = np.zeros([info["height"], info["width"], self.num_classes])
        for i in np.arange(self.num_classes):
            masks_of_same_class = mask[:, :, mask_classes == (i+1)]
            for single_mask_index in np.arange(masks_of_same_class.shape[2]):
                united_masks[:,:,i] = np.logical_or(united_masks[:,:,i], masks_of_same_class[:,:,single_mask_index])
        # clean each mask from intersections with united_masks
        classes_array = np.array([self.class_name2id[name] for name in self.class_names])
        for i in np.arange(mask.shape[2]):
            # stronger_classes = np.unique(mask_classes[mask_classes > mask_classes[i]])
            stronger_classes = classes_array[classes_array > mask_classes[i]]
            stronger_classes -= 1  # change from class number to index in united_masks (starts from 0)
            curr_mask = mask[:, :, i]
            for class_index in stronger_classes:
                curr_mask[np.logical_and(curr_mask, united_masks[:,:,class_index])] = 0
            mask[:, :, i] = curr_mask
        # remove other from masks
        mask = mask[:, :, mask_classes != self.class_name2id["other"]]
        mask_classes = mask_classes[mask_classes != self.class_name2id["other"]]

        # Return mask, and array of class IDs of each instance. Since we have
        # one class ID only, we return an array of 1s
        for i in np.arange(mask.shape[2]):
            mask_copy = mask.copy()
            current_mask = mask_copy[:,:,i]
            current_mask[ current_mask == 1 ] = 255
            dir_to_save = r'D:\Nati\Itamar_n_Shai\Datasets\DataSynth\occlusion_result'
            image_path = os.path.join(dir_to_save, str(int(image_id)) + "_" + str(i) + '.png')
            cv2.imwrite(image_path, current_mask)

        return mask, mask_classes

    def image_reference(self, image_id):
        """Return the path of the image."""
        info = self.image_info[image_id]
        if info["source"] == "PDL1":
            return info["path"]
        else:
            super(self.__class__, self).image_reference(image_id)