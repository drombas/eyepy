import logging
from pathlib import Path
from typing import List, Union

import imageio.v2 as imageio
import numpy as np

from eyepy import EyeBscanMeta
from eyepy import EyeVolume
from eyepy import EyeVolumeMeta

from .he import HeE2eReader
from .he import HeVolReader
from .he import HeVolWriter
from .he import HeXmlReader

logger = logging.getLogger("eyepy.io")


def import_heyex_e2e(path: Union[str, Path]) -> EyeVolume:
    """ Read a Heyex E2E file

    This function is a thin wrapper around the HeE2eReader class and
    returns the first of potentially multiple OCT volumes. If you want to
    read all volumes, or need more control, you can use the
    [HeE2eReader][eyepy.io.he.e2e_reader.HeE2eReader] class directly.

    Args:
        path: Path to the E2E file

    Returns:
        Parsed data as EyeVolume object

    """
    reader = HeE2eReader(path)
    if len(reader.series) < 1:
        logger.info(
            f"There are {len(reader.series)} Series stored in the E2E file. If you want to read all of them, use the HeE2eReader class directly."
        )
    with reader as open_reader:
        ev = open_reader.volume
    return ev


def import_heyex_xml(path: Union[str, Path]) -> EyeVolume:
    """ Read a Heyex XML file

    This function is a thin wrapper around the HeXmlReader class
    which you can use directly if you need more control.

    Args:
        path: Path to the XML file or the folder containing the XML file

    Returns:
        Parsed data as EyeVolume object

    """
    return HeXmlReader(path).volume


def import_heyex_vol(path: Union[str, Path]) -> EyeVolume:
    """ Read a Heyex VOL file

    This function is a thin wrapper around the HeVolReader class
    which you can use directly if you need more control.

    Args:
        path: Path to the VOL file

    Returns:
        Parsed data as EyeVolume object

    """
    return HeVolReader(path).volume


def import_bscan_folder(path: Union[str, Path]) -> EyeVolume:
    """ Read B-Scans from a folder

    This function can be used to read B-scans from a folder in case that
    there is no additional metadata available.

    Args:
        path: Path to the folder containing the B-Scans

    Returns:
        Parsed data as EyeVolume object

    """
    path = Path(path)
    img_paths = sorted(list(path.iterdir()))
    img_paths = [
        p for p in img_paths if p.is_file()
        and p.suffix.lower() in [".jpg", ".jpeg", ".tiff", ".tif", ".png"]
    ]

    images = []
    for p in img_paths:
        image = imageio.imread(p)
        if len(image.shape) == 3:
            image = image[..., 0]
        images.append(image)

    volume = np.stack(images, axis=0)
    bscan_meta = [
        EyeBscanMeta(start_pos=(0, i),
                     end_pos=(volume.shape[2] - 1, i),
                     pos_unit="pixel")
        for i in range(volume.shape[0] - 1, -1, -1)
    ]
    meta = EyeVolumeMeta(scale_x=1,
                         scale_y=1,
                         scale_z=1,
                         scale_unit="pixel",
                         bscan_meta=bscan_meta)

    return EyeVolume(data=volume, meta=meta)


def import_duke_mat(path: Union[str, Path]) -> EyeVolume:
    """ Import an OCT volume from the Duke dataset

    The dataset is available at https://people.duke.edu/~sf59/RPEDC_Ophth_2013_dataset.htm
    OCT volumes are stored as .mat files which are parsed by this function and returned as
    EyeVolume object.

    Args:
        path: Path to the .mat file

    Returns:
        Parsed data as EyeVolume object

    """
    import scipy.io as sio

    loaded = sio.loadmat(path)
    volume = np.moveaxis(loaded["images"], -1, 0)
    layer_maps = np.moveaxis(loaded["layerMaps"], -1, 0)

    bscan_meta = [
        EyeBscanMeta(
            start_pos=(0, 0.067 * i),
            end_pos=(0.0067 * (volume.shape[2] - 1), 0.067 * i),
            pos_unit="mm",
        ) for i in range(volume.shape[0] - 1, -1, -1)
    ]
    meta = EyeVolumeMeta(
        scale_x=0.0067,
        scale_y=0.0045,  # https://retinatoday.com/articles/2008-may/0508_10-php
        scale_z=0.067,
        scale_unit="mm",
        bscan_meta=bscan_meta,
        age=loaded["Age"],
    )

    volume = EyeVolume(data=volume, meta=meta)
    names = {0: "ILM", 1: "IBRPE", 2: "BM"}
    for i, height_map in enumerate(layer_maps):
        volume.add_layer_annotation(
            np.flip(height_map, axis=0),
            name=names[i],
        )

    return volume


def import_retouch(path: Union[str, Path]) -> EyeVolume:
    """ Import an OCT volume from the Retouch dataset

    The dataset is available upon request at https://retouch.grand-challenge.org/
    Reading the data requires the ITK library to be installed. You can install it with pip:

    `pip install itk`

    Args:
        path: Path to the folder containing the OCT volume

    Returns:
        Parsed data as EyeVolume object

    """
    import itk

    path = Path(path)
    data = itk.imread(str(path / "oct.mhd"))

    bscan_meta = [
        EyeBscanMeta(
            start_pos=(0, data["spacing"][0] * i),
            end_pos=(data["spacing"][2] * (data.shape[2] - 1),
                     data["spacing"][0] * i),
            pos_unit="mm",
        ) for i in range(data.shape[0] - 1, -1, -1)
    ]

    meta = EyeVolumeMeta(
        scale_x=data["spacing"][2],
        scale_y=data["spacing"][1],
        scale_z=data["spacing"][0],
        scale_unit="mm",
        bscan_meta=bscan_meta,
    )
    # Todo: Add intensity transform instead. Topcon and Cirrus are stored as UCHAR while heidelberg is stored as USHORT
    data = (data[...].astype(float) / np.iinfo(data[...].dtype).max *
            255).astype(np.uint8)
    eye_volume = EyeVolume(data=data[...], meta=meta)

    if (path / "reference.mhd").is_file():
        annotation = itk.imread(str(path / "reference.mhd"))
        eye_volume.add_pixel_annotation(np.equal(annotation, 1),
                                        name="IRF",
                                        current_color="FF0000")
        eye_volume.add_pixel_annotation(np.equal(annotation, 2),
                                        name="SRF",
                                        current_color="0000FF")
        eye_volume.add_pixel_annotation(np.equal(annotation, 3),
                                        name="PED",
                                        current_color="FFFF00")

    return eye_volume
