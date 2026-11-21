Installation
============

Requirements
------------

* **Python**: 3.12 or higher
* **SQLAlchemy**: 2.0 or higher (for ORM integration)
* **boto3**: 1.34 or higher (optional, only for the S3 backend: ``pip install "granite-storage[s3]"``)

Package Installation
--------------------

**Using pip**:

.. code-block:: bash

   pip install granite-storage

**Using UV** (fastest):

.. code-block:: bash

   uv add granite-storage

**Using Poetry**:

.. code-block:: bash

   poetry add granite-storage

Development Installation
------------------------

.. code-block:: bash

   git clone https://github.com/granite-stack/granite-storage.git
   cd granite-storage
   uv sync

Optional Extras
---------------

``s3``
    Installs ``boto3`` for ``S3StorageBackend``
    (``pip install "granite-storage[s3]"``). Without it the local backend works
    normally and importing ``S3StorageBackend`` raises an ``ImportError`` that
    names the extra.
