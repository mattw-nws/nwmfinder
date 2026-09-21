Usage
=====

Installation
------------

.. code-block:: bash

   pip install -e .

Locating the latest cycle
--------------------------

.. code-block:: python

   from nwmfinder import NwmFinder, Downloader

   finder = NwmFinder()
   cycles = finder.locate("short_range", "NOMADS")
   cycle = cycles[0]

   downloader = Downloader(cache_dir="./cache")
   results = downloader.download_references(cycle.files)

Locating a historical date range
---------------------------------

.. code-block:: python

   from datetime import datetime, timezone
   from nwmfinder import NwmFinder

   finder = NwmFinder()
   t0 = datetime(2023, 6, 1, 0, tzinfo=timezone.utc)
   tend = datetime(2023, 6, 1, 6, tzinfo=timezone.utc)
   cycles = finder.locate_range(t0, tend)
