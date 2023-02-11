import { styled } from "@nextui-org/react"
import { Header } from './header';
import { Cell } from './notebook';
import { useState } from 'react';
import { Container } from "@nextui-org/react";

const Box = styled("div", {
    boxSizing: "border-box",
});


export function Layout({ children }) {


    const [cells, setCells] = useState([]);

    function handleChange() {

    }

    function handleAdd(type) {
        const newList = cells.concat({ type: type, id: cells.length });

        setCells(newList);

    }

    function handleDelete(id) {
        const newList = cells.filter((item) => item.id !== id);

        setCells(newList);
    }


    return (
        <Box
            css={{
                maxW: "100%"
            }}
        >
            <Header onNewClick={(type) => handleAdd(type)} />
            <Container md>
                {cells.map((item) => (
                    <Cell key={item.id} cell={item} onDelete={handleDelete} />
                ))}
            </Container>
        </Box >
    );
}
