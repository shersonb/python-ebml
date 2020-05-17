# python-ebml
Yet Another EBML module for Python

## Usage

```python

from ebml.head import EBMLHead

head = EBMLHead(docType="matroska", docTypeReadVersion=2, docTypeVersion=4,
        ebmlMaxIDLength=4, ebmlMaxSizeLength=8, ebmlReadVersion=1, ebmlVersion=1)

head.toBytes()                                                                                                                                                                                                                           
# Returns b'\x1aE\xdf\xa3\xa3B\x86\x81\x01B\xf7\x81\x01B\xf2\x81\x04B\xf3\x81\x08B\x82\x88matroskaB\x87\x81\x04B\x85\x81\x02'

```

See ebml/head.py for an example of subclassing.

## Contributing
Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

Please make sure to update tests as appropriate.

## License
[MIT](https://choosealicense.com/licenses/mit/)

